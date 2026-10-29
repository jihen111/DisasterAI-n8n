"""Turning the workflow's JSON into what a person reads. Pure functions, no Streamlit, so they are tested offline."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "rag" / "corpus"

SOURCE_LABELS = {"report": "From the report", "image": "From the image", "knowledge_base": "From the knowledge base", "model_inference": "Model inference"}
SOURCE_ICONS = {"report": "📝", "image": "🖼️", "knowledge_base": "📚", "model_inference": "🤖"}

IMAGE_MESSAGES = {
    "analysed": ("success", "The image was analysed and used in this report."),
    "analysis_failed": ("warning", "An image was sent but the image analysis failed. This report uses the text only."),
    "unusable": ("warning", "The image could not be used (too dark, blurred, or not a scene). This report uses the text only."),
    "not_provided": ("info", "No image was sent. This report uses the text only."),
}


def status_banner(body):
    """(level, title, message) for the top of the result. level is a Streamlit alert: success | warning | error | info."""
    status = (body or {}).get("status")
    degraded = (body or {}).get("degraded_steps") or []
    validation = (body or {}).get("validation") or {}
    if status == "rejected":
        return "error", "The workflow rejected this input", str(body.get("error") or "No reason given.")
    if status == "ok":
        return "success", "Report produced, all automatic checks passed", "Nothing was degraded."
    if status == "flagged":
        n = len(validation.get("violations") or [])
        title = f"Report produced, but {n} automatic check{'s' if n != 1 else ''} failed"
        if validation.get("repair_discarded"):
            return "warning", title, "An automatic repair was tried and made the report worse (it dropped required parts), so the original report is shown with its original problem."
        return "warning", title, ("Read it with care: the guardrails found a problem that the repair pass did not remove." if validation.get("repaired") else "The guardrails found a problem.")
    if status == "degraded":
        steps = ", ".join(dict.fromkeys(d.get("step", "?") for d in degraded)) or "one step"
        return "warning", "Report produced, with degraded steps", f"Steps with a problem: {steps}. Details are in the Pipeline tab."
    if status == "needs_more_information":
        return "info", "More information needed", "The report is too vague to classify. Nothing was guessed: the missing information is listed below."
    if not (body or {}).get("report"):
        return "error", "No report was produced", "The report agent failed even after its retry."
    return "info", f"Status: {status}", ""


def image_message(report, sent_image):
    status = (report or {}).get("image_status") or ("not_provided" if not sent_image else "analysis_failed")
    return IMAGE_MESSAGES.get(status, ("info", f"Image status: {status}")) + (status,)


def chips(source):
    return f"{SOURCE_ICONS.get(source, '•')} {SOURCE_LABELS.get(source, source or 'unknown')}"


def timeline_rows(models_used):
    """One row per model call: step, model, seconds, failed attempts (rate limits, errors) before the answer."""
    rows = []
    for m in models_used or []:
        failed = m.get("failed_attempts") or []
        rows.append({"step": m.get("step", "?"), "seconds": float(m.get("seconds") or 0.0), "model": (m.get("model") or m.get("error") or "-").split("/")[-1],
                     "provider": m.get("provider") or "-", "failed attempts": len(failed), "failed detail": "; ".join(failed)[:200]})
    return rows


def slowest_step(rows):
    return max(rows, key=lambda r: r["seconds"]) if rows else None


def degraded_lines(degraded_steps):
    return [f"{d.get('step', '?')}: {d.get('reason', '')}" for d in degraded_steps or []]


def repair_discarded_problems(validation):
    """The problems of a repaired report that the workflow threw away because it was worse than the original: [(check, message)]."""
    v = validation or {}
    if not v.get("repair_discarded"):
        return []
    return [(x.get("check", "?"), x.get("message", "")) for x in v.get("repair_violations") or []]


def validation_view(validation):
    """(status, repaired, [(check, message)], [(check, message)] first violations before the repair pass)."""
    v = validation or {}
    now = [(x.get("check", "?"), x.get("message", "")) for x in v.get("violations") or []]
    first = [(x.get("check", "?"), x.get("message", "")) for x in v.get("first_violations") or []]
    return v.get("status", "not run"), bool(v.get("repaired")), now, first


_ENTRIES = None


def load_entries():
    """Entry id -> {title, text, source, language}, read from rag/corpus/*/*_kb.md. Used to show the passage behind a recommendation."""
    global _ENTRIES
    if _ENTRIES is None:
        _ENTRIES = {}
        for path in sorted(CORPUS.glob("*/*_kb.md")):
            lang = path.parent.name
            for block in re.split(r"(?m)^## ", path.read_text(encoding="utf-8"))[1:]:
                head, _, rest = block.partition("\n")
                m = re.match(r"([A-Z]{2}-\d+) (.*)", head)
                if not m:
                    continue
                lines = [line for line in rest.strip().splitlines() if line.strip()]
                body = [line for line in lines if not line.startswith(("Source:", "Origin of the sources:", "Team note"))]
                source = next((line for line in lines if line.startswith("Source:")), "")
                _ENTRIES[m.group(1)] = {"title": m.group(2), "text": "\n\n".join(body), "source": source.replace("Source: ", ""), "language": lang}
    return _ENTRIES


def entry(entry_id):
    return load_entries().get(entry_id)


def check_expected(expected, body):
    """Compare a run with the expected values of a fixed incident: list of (label, ok). Same rules as scripts/run_incidents.py."""
    out = []
    if not expected:
        return out
    if "incident_type" in expected:
        out.append((f"Incident type is {expected['incident_type']}", body.get("incident_type") == expected["incident_type"]))
    if "severity_acceptable" in expected:
        out.append((f"Severity is one of {', '.join(expected['severity_acceptable'])}", body.get("severity") in expected["severity_acceptable"]))
    out.append(("A report was produced", bool(body.get("report_markdown"))))
    return out


def typical_seconds(history_records):
    """Median wall time of earlier successful runs, for the honest progress text. None when there is no history."""
    secs = sorted(r["seconds"] for r in history_records if r.get("kind") in ("ok", "degraded", "flagged") and r.get("seconds"))
    return secs[len(secs) // 2] if secs else None


def short(text, n=120):
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)
