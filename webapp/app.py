"""
Operator dashboard for the node-runner raffle.

A thin web layer over the node_raffle package: it drives the same five-stage
loop as the CLI (init -> enter -> close -> publish -> draw) with a UI instead
of command-line flags. Run it locally -- it handles your organizer secret key
during the publish step and is not meant to be exposed to the public internet.

    pip install flask
    python webapp/app.py
    # open http://127.0.0.1:5000

Public entrants don't need this; they verify draws with the standalone
verify.html, which trusts no server at all.

Basic auth
----------
Set RAFFLE_PASSWORD in the environment (or .env) to require a password for
every operator-dashboard request. Leave it blank (the default) for local-only
use with no authentication.
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

# Make the sibling node_raffle package importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    Response,
)

from node_raffle import draw
from node_raffle.check_node import check_node
from node_raffle.registry import RaffleRound, Store, Status

STATE_FILE = os.environ.get("RAFFLE_STATE", "raffle_state.json")
_PASSWORD = os.environ.get("RAFFLE_PASSWORD", "").strip()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-only-not-for-production")


# ---------------------------------------------------------------------------
# Basic auth
# ---------------------------------------------------------------------------

def _check_auth(password: str) -> bool:
    return password == _PASSWORD


def _auth_required(f):
    """Decorator: require HTTP Basic Auth when RAFFLE_PASSWORD is set."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not _PASSWORD:
            return f(*args, **kwargs)
        auth = request.authorization
        if auth and _check_auth(auth.password):
            return f(*args, **kwargs)
        return Response(
            "Operator dashboard — authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="Raffle operator"'},
        )
    return decorated


def _apply_auth(app_):
    """Apply auth to every route on the app."""
    app_.before_request(_gate)

_auth_checked = False

def _gate():
    global _auth_checked
    if not _PASSWORD:
        return None
    # allow the verifier page through without a password — it's public
    if request.path == "/verify.html" or request.path.startswith("/enter/"):
        return None
    auth = request.authorization
    if auth and _check_auth(auth.password):
        return None
    return Response(
        "Operator dashboard — authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Raffle operator"'},
    )

app.before_request(_gate)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def store() -> Store:
    return Store(STATE_FILE)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/verify.html")
def verifier():
    from flask import send_from_directory
    return send_from_directory(Path(__file__).resolve().parent.parent, "verify.html")


@app.route("/")
def index():
    s = store()
    rounds = [s.load(rid) for rid in s.list_rounds()]
    rounds.sort(key=lambda r: r.opened_at, reverse=True)
    return render_template("index.html", rounds=rounds, Status=Status)


@app.route("/round/<round_id>")
def round_detail(round_id):
    try:
        rnd = store().load(round_id)
    except KeyError:
        flash(f"No round named {round_id!r}.", "error")
        return redirect(url_for("index"))
    return render_template("round.html", r=rnd, Status=Status)


@app.route("/create", methods=["POST"])
def create():
    s = store()
    round_id = request.form.get("round_id", "").strip()
    if not round_id:
        flash("Give the round a name.", "error")
        return redirect(url_for("index"))
    if round_id in s.list_rounds():
        flash(f"Round {round_id!r} already exists.", "error")
        return redirect(url_for("index"))
    try:
        draw_height = int(request.form["draw_height"])
    except (KeyError, ValueError):
        flash("Draw block height must be a number.", "error")
        return redirect(url_for("index"))
    extra = int(request.form.get("extra_blocks", 0) or 0)
    max_per_ip = int(request.form.get("max_entries_per_ip", 1) or 1)

    s.save(RaffleRound(
        round_id=round_id,
        draw_block_height=draw_height,
        extra_blocks=extra,
        max_entries_per_ip=max_per_ip,
    ))
    flash(f"Round {round_id!r} opened. Announce block {draw_height} publicly now.", "ok")
    return redirect(url_for("round_detail", round_id=round_id))


@app.route("/round/<round_id>/enter", methods=["POST"])
def enter(round_id):
    s = store()
    rnd = s.load(round_id)
    npub = request.form.get("npub", "").strip()
    ip = request.form.get("ip", "").strip()
    port = int(request.form.get("port", 8333) or 8333)
    skip = request.form.get("skip_check") == "on"

    if not npub:
        flash("An npub is required.", "error")
        return redirect(url_for("round_detail", round_id=round_id))

    if not skip:
        if not ip:
            flash("Provide the node IP, or check 'skip node check'.", "error")
            return redirect(url_for("round_detail", round_id=round_id))
        result = check_node(ip, port)
        if not result.reachable:
            flash(f"Node check failed ({result.error}). Entry not counted.", "error")
            return redirect(url_for("round_detail", round_id=round_id))
        flash(f"Node verified: {result.user_agent} at height {result.start_height}.", "ok")

    try:
        added = rnd.add_entry(npub, source_ip=ip)
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("round_detail", round_id=round_id))
    s.save(rnd)
    flash("Entry counted." if added else "That npub already entered.", "ok" if added else "warn")
    return redirect(url_for("round_detail", round_id=round_id))


@app.route("/round/<round_id>/close", methods=["POST"])
def close(round_id):
    s = store()
    rnd = s.load(round_id)
    try:
        commitment = rnd.close()
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("round_detail", round_id=round_id))
    s.save(rnd)
    flash(f"Sealed {len(rnd.entries)} entries. Commitment: {commitment[:16]}…", "ok")
    return redirect(url_for("round_detail", round_id=round_id))


@app.route("/round/<round_id>/publish", methods=["POST"])
def publish(round_id):
    s = store()
    rnd = s.load(round_id)
    nsec = request.form.get("nsec", "").strip()
    if not nsec:
        flash("Your Nostr secret key is needed to sign the entry list.", "error")
        return redirect(url_for("round_detail", round_id=round_id))
    try:
        from node_raffle.nostr_publish import publish_entry_list, DEFAULT_RELAYS
        relays_raw = request.form.get("relays", "").strip()
        relays = [r.strip() for r in relays_raw.splitlines() if r.strip()] or DEFAULT_RELAYS
        serialized = draw.serialize(rnd.entries)
        event_id = publish_entry_list(serialized, nsec, rnd.round_id, relays)
        rnd.mark_published(event_id, relays)
        s.save(rnd)
        flash(f"Published. Nostr event id: {event_id}", "ok")
    except Exception as e:
        flash(f"Publish failed: {e}", "error")
    return redirect(url_for("round_detail", round_id=round_id))


@app.route("/round/<round_id>/draw", methods=["POST"])
def do_draw(round_id):
    s = store()
    rnd = s.load(round_id)
    pasted = request.form.get("block_hash", "").strip()
    rpc = request.form.get("rpc", "").strip()
    try:
        if pasted:
            hashes = [h.strip() for h in pasted.splitlines() if h.strip()]
        else:
            from node_raffle.blockchain import Mempool, BitcoinCoreRPC
            src = BitcoinCoreRPC(rpc) if rpc else Mempool()
            tip = src.tip_height()
            last_needed = rnd.draw_block_height + rnd.extra_blocks
            if tip < last_needed:
                flash(f"Draw block not mined yet (tip {tip}, need {last_needed}).", "warn")
                return redirect(url_for("round_detail", round_id=round_id))
            hashes = src.block_hashes(rnd.draw_block_height, rnd.extra_blocks + 1)

        result = draw.pick_winner(rnd.entries, hashes)
        rnd.record_draw(result)
        s.save(rnd)
        flash(f"Winner drawn: {result.winner}", "ok")
    except Exception as e:
        flash(f"Draw failed: {e}", "error")
    return redirect(url_for("round_detail", round_id=round_id))


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))


# ---------------------------------------------------------------------------
# Public routes (no auth required)
# ---------------------------------------------------------------------------

@app.route("/enter/<round_id>")
def public_enter_form(round_id):
    """Public-facing entry page for node operators."""
    try:
        rnd = store().load(round_id)
    except KeyError:
        return f"Round {round_id!r} not found.", 404
    return render_template("enter.html", r=rnd, Status=Status)


@app.route("/enter/<round_id>", methods=["POST"])
def public_enter(round_id):
    """Handle a self-service entry submission."""
    s = store()
    try:
        rnd = s.load(round_id)
    except KeyError:
        return f"Round {round_id!r} not found.", 404

    npub = request.form.get("npub", "").strip()
    ip = request.form.get("ip", "").strip()
    port = int(request.form.get("port", 8333) or 8333)

    if not npub:
        flash("An npub is required.", "error")
        return redirect(url_for("public_enter_form", round_id=round_id))
    if not ip:
        flash("Your node IP address is required.", "error")
        return redirect(url_for("public_enter_form", round_id=round_id))

    result = check_node(ip, port)
    if not result.reachable:
        flash(
            f"Could not reach a Bitcoin node at {ip}:{port} — {result.error}. "
            "Make sure port 8333 is open and your node is synced.",
            "error",
        )
        return redirect(url_for("public_enter_form", round_id=round_id))

    try:
        added = rnd.add_entry(npub, source_ip=ip)
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("public_enter_form", round_id=round_id))

    s.save(rnd)
    if added:
        flash(
            f"You're in! Node verified ({result.user_agent}, height {result.start_height}). "
            f"Your npub has been added to the entry list.",
            "ok",
        )
    else:
        flash("That npub is already entered in this round.", "warn")
    return redirect(url_for("public_enter_form", round_id=round_id))
