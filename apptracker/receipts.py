"""Application receipts: "we received your application" mail, matched to rows.

Firms send a receipt when an application goes in ("Your application has been
received by ..."). Whatever reads your mail (a script, or an assistant with
mail access) runs the searches `confirm query` prints, saves the messages as
JSON, and `confirm ingest` matches each receipt to its application: it sets
`confirmed` (and `applied`, if the box was never ticked). A finished Suited
assessment ticks that checklist item. Anything it cannot pin to one
application waits in `confirm list --review`, and an application started but
never submitted ("click here to continue your application") is flagged after
two days. This module never reads mail itself.

A saved message is {message_id, date, from, from_name, subject, body}. The
reader may add `kind` (one of KINDS) and `program` after reading it; a label
wins over the phrase rules here, which on their own only confirm an
application whose box is already ticked.
"""

import datetime
import email.utils
import html
import re

from . import applications as A
from . import firms, store
from .checklist import checklist_done, checklist_str
from .config import settings

CONF_COLS = ["message_id", "date", "sender", "subject", "kind", "firm", "app_id", "result",
             "evidence", "logged", "resolved"]
STARTED_GRACE = 2      # days a started-but-not-submitted application waits before it is flagged

RECEIVED = re.compile(
    r"\bapplication\b(?:\W+\w+){0,14}?\W+(?:has been|have been|was|is)\s+(?:received|submitted|completed?)\b|"
    r"\b(?:received|receipt of) your (?:\w+ ){0,2}(?:application|materials|submission|resume|transcripts?)\b|"
    r"\b(?:your )?materials (?:have been|were) received\b|"
    r"\bthanks? (?:you )?for (?:submitting|completing) your (?:\w+ ){0,3}application\b|"
    r"\bthanks? (?:you )?for (?:applying|your application)\b|"
    r"\bsuccessfully (?:submitted|applied)\b|\byou(?:'ve| have) applied (?:to|for)\b|"
    r"\bconfirm(?:s|ation)? (?:that|of) (?:you applied|your application)\b", re.I)
# a subject that says so is enough on its own ("Application Received - 2028 Summer Associate Program")
RECEIVED_SUBJECT = re.compile(r"\bapplication (?:received|submitted|confirmation|acknowledg(?:e)?ment)\b", re.I)
# words before a match in its sentence that make it a description of the process
# ("once we have received your application...", "if selected, we will contact you to schedule an interview")
CONDITIONAL = re.compile(r"\b(?:once|after|when|if|until|before|whether|should|unless|in the event|not yet|haven't|have not)\b", re.I)
# a sentence about an event, a sign-up or a mailing list is not about an application
EVENTISH = re.compile(r"\b(?:regist(?:er|ering|ered|ration)|rsvp|attend(?:ance|ing)?|reception|webinar|info(?:rmation)? session|"
                      r"talent (?:community|network)|interest form|mailing list|newsletter|events?|summit|cancel+ed|"
                      r"workshop|open house|boot ?camp|networking|panel|dinner|luncheon|happy hour|series|walk-?around)\b", re.I)
# in a sentence about an event, only these say it is about a summer job ("application to attend" doesn't)
JOB_WORDS = re.compile(r"\bsummer associate|\bsummer program|\bposition\b|\bfellowship\b|\bassociate program\b", re.I)
PROGRAM_WORDS = re.compile(r"\bappl(?:y|ied|ying|ication)|\bsummer associate|\bsummer program|\bprogram\b|\bposition\b|\bfellowship|\bwill be reviewed\b|\bfor (?:our )?review\b|\bconsideration\b", re.I)
# the whole message is a sign-up, not an application
SIGNUP = re.compile(r"\btalent (?:community|network)\b|\binterest form\b|\bwhen (?:the )?applications? (?:open|go live)\b|"
                    r"\bjoin(?:ing|ed)? our (?:mailing|talent|candidate)\b", re.I)
STARTED = re.compile(r"\b(?:continue|complete|finish) your application\b|\bclick here to apply\b|\bto fill out an application\b|"
                     r"\b(?:validate|verify) your email\b|\bexpressing interest in the following position|"
                     r"\bapplication is (?:not (?:yet )?complete|incomplete)\b|\bincomplete application\b", re.I)
ANNOUNCE = re.compile(r"\b(?:apply now|applications? (?:are |is )?(?:now )?open|now open|now accepting|you'?re invited|"
                      r"rsvp|webinar|reception|info(?:rmation)? session|newsletter|reminder|waitlist|"
                      r"mailing list|registration|registered|registering|events?|talent community|digest|faq|"
                      r"questions|answered)\b", re.I)
SUITED = re.compile(r"\bsuited(?:'s)? (?:assessment|profile|candidate|platform|account|link)|\b(?:via|by|from|with|through) suited\b|"
                    r"\buses suited\b", re.I)
SUITED_DONE = re.compile(r"\bthanks? (?:you )?for (?:completing|taking|finishing) (?:the|your) (?:suited )?assessment\b|"
                         r"\b(?:you(?:'ve| have)|has been) completed (?:your|the) (?:suited )?assessment\b|"
                         r"\bassessment (?:is |has been )?(?:complete[d]?|submitted)\b|\bresults have been shared\b", re.I)
SUITED_ASK = re.compile(r"\binvit\w*|\bplease complete\b|\bcomplete (?:your|the|a) (?:suited )?assessment\b|\bbegin\b|"
                        r"\bget started\b|\bstart (?:your|the)\b|\btake the (?:suited )?assessment\b|\bnot (?:yet )?completed\b|"
                        r"\breminder\b|\bmake sure you have completed\b|\bask all candidates\b|\bnow complete\b", re.I)
STATUS = re.compile(
    r"\binvite you to (?:a |an |our )?(?:\w+[ -]){0,4}interviews?\b|\binvitation to (?:a |an )?(?:\w+[ -]){0,2}interview\b|"
    r"\b(?:schedule|scheduling|book|select a time for) (?:an|your|a) (?:\w+[ -]){0,2}interview\b|"
    r"\bwould like to (?:meet with|interview|speak with) you\b|\bcallback interviews?\b|"
    r"\bwe regret\b(?! that we (?:cannot|can't|are unable to|will not be able to) (?:respond|reply|acknowledge))|\bregret to inform\b|"
    r"\bunable to (?:offer|extend|move forward)\b|\bnot (?:be )?(?:moving|able to move|to move) forward\b|"
    r"\bwon't be moving forward\b|\bnot be inviting\b|\bdecided not to (?:proceed|move|invite|extend)\b|"
    r"\bpursue other (?:candidates|applicants)\b|\bnot in a position to offer\b|\bcannot offer\b|"
    r"\binvite you (?:to|for) (?:a |an )?(?:\w+[ -]){0,3}interview|\bselected for (?:a |an )?(?:\w+[ -]){0,3}interview\b|"
    r"\bnot (?:be )?able to offer\b|\bpursue other candidates\b|\bnot (?:been )?selected\b|\bnot be extending\b|"
    r"\b(?:pleased|delighted|happy|thrilled) to (?:offer you|extend (?:you )?an offer)\b|\boffer of (?:summer )?employment\b", re.I)
STATUS_SUBJECT = re.compile(r"\binterview\b|\bcallback\b|\boffer\b|\bdecision\b|\bupdate on your application\b|"
                            r"\bapplication (?:status|update)\b", re.I)
# a receipt for one of these goes to the row whose program names it, or to you
SPECIAL = re.compile(r"\b(fellow\w*|scholar\w*|diversity|pro bono|patent|lcld|leadership|inclusion)\b", re.I)
EEO = re.compile(r"\bcommitted to (?:diversity|inclusion)|\bequal (?:employment )?opportunity\b|\bself-identif", re.I)
KINDS = ("application", "status", "started", "assessment", "assessment_invite", "other")
LEAD = 700             # a receipt says so up front; a newsletter buries "received your application" in a FAQ
DUPLICATE_DAYS = 2     # a second receipt within this many days is the same application (ATS plus recruiting)
OFFICE_CUES = [("DC", re.compile(r"\bwashington\b|\bD\.C\.(?!\w)|\bDC\b")), ("NY", re.compile(r"\bnew york\b|\bNYC?\b", re.I)),
               ("LA", re.compile(r"\blos angeles\b|\bcentury city\b|\bL\.A\.(?!\w)|\bLA\b")),
               ("SF", re.compile(r"\bsan francisco\b|\bSF\b")), ("BOS", re.compile(r"\bboston\b", re.I)),
               ("CHI", re.compile(r"\bchicago\b", re.I))]
FIRST_WINDOW = 60      # days back the first receipt search reaches, unless receipts_since says


def _plain(body):
    """Message text without HTML, entities or runs of whitespace."""
    s = body or ""
    if "<" in s and ">" in s:
        s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
        s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _sentence(text, m):
    """The sentence (or subject line) a match sits in."""
    lo = max(text.rfind(c, 0, m.start()) for c in ".!?|") + 1
    ends = [i for i in (text.find(c, m.end()) for c in ".!?|") if i >= 0]
    return text[lo:(min(ends) + 1) if ends else len(text)].strip()


def _hit(rx, text, conditional=False, about=None):
    """First match of rx in text that is a statement, not a condition or a
    question ('Q: How do I know my application was received?'). With `about`,
    the match's sentence must be about an application, not an event, a
    sign-up or a profile ('received your submission' alone proves nothing)."""
    for m in rx.finditer(text):
        sent = _sentence(text, m)
        lo = max(text.rfind(c, 0, m.start()) for c in ".!?|") + 1
        if conditional and CONDITIONAL.search(text[lo:m.start()]):
            continue
        if sent.endswith("?") or re.match(r"^(?:Q|Question)\s*[:.]", sent, re.I):
            continue
        if about is not None:
            if EVENTISH.search(sent) and (not JOB_WORDS.search(sent) or re.search(r"\bto attend\b|\bspot at\b", sent, re.I)):
                continue
            subj = text.split(" | ", 1)[0]
            if re.search(r"submission|successfully|resume|transcript|materials", m.group(0), re.I) \
                    and (not (PROGRAM_WORDS.search(sent) or PROGRAM_WORDS.search(subj))
                         or re.search(r"\b(?:profile|registration|rsvp)\b", sent, re.I)):
                continue
        return m
    return None


def _future(text, m):
    """'we will contact you to schedule an interview if selected' describes the
    process; 'we would like to invite you to interview' and 'we will not be
    moving forward' are news."""
    sent = _sentence(text, m)
    return bool(re.search(r"\b(?:will|may|might|if|should|once|when)\b", sent, re.I)) and \
        not re.search(r"\bwould like\b|\bpleased\b|\bdelighted\b|\bregret\b|\bunable\b|\bnot (?:be )?able\b|"
                      r"\bwill not\b|\bwon't\b|\bcannot\b|\bhave been selected\b", sent, re.I)


def _status_hit(text):
    """News in the text, read sentence by sentence. 'After careful
    consideration' and 'after reviewing your application' open decisions; they
    are not conditions."""
    for m in STATUS.finditer(text):
        sent = _sentence(text, m)
        lo = max(text.rfind(c, 0, m.start()) for c in ".!?|") + 1
        before = re.sub(r"\b(?:after|following|upon)\s+(?:careful\s+)?(?:consideration|review(?:ing)?(?: of)?(?: your application)?)",
                        "", text[lo:m.start()], flags=re.I)
        if CONDITIONAL.search(before) or sent.endswith("?") or EVENTISH.search(sent) or _future(text, m):
            continue
        return m
    return None


def classify(msg):
    """(kind, evidence): status, application, assessment, assessment_invite,
    started or other. Only the subject and the opening of the body count.
    Interview and decision news is checked first: rejections and invitations
    usually open with 'thank you for your application' too."""
    subject = _plain(msg.get("subject"))
    lead = _plain(msg.get("body"))[:LEAD]
    text = subject + " | " + lead
    got = _status_hit(text)
    if got:
        return "status", got.group(0)
    if STATUS_SUBJECT.search(subject) and not ANNOUNCE.search(subject) and not EVENTISH.search(subject):
        return "status", "subject: " + STATUS_SUBJECT.search(subject).group(0)
    # the Suited platform, not the word ("better suited to litigation"); a
    # Suited message is about the assessment, never an application receipt
    from_suited = "suited" in (msg.get("from") or "").lower().rpartition("@")[2] or \
        re.search(r"\bsuited\b", _plain(msg.get("from_name")), re.I)
    if from_suited or re.search(r"\bsuited\b", subject, re.I):
        done_in_subject = SUITED_DONE.search(subject) if not subject.rstrip().endswith("?") else None
        done = _hit(SUITED_DONE, text, conditional=True)
        ask = _hit(SUITED_ASK, text)
        if done_in_subject or (done and not ask):
            return "assessment", "Suited: " + (done_in_subject or done).group(0)
        return "assessment_invite", "Suited: " + (ask.group(0) if ask else "assessment")
    if SIGNUP.search(text):
        return "other", ""
    # "thank you for applying for a spot at our networking reception": the thing
    # applied to is an event, so the rest of the message is about the event too
    for sent in re.split(r"(?<=[.!?|])\s+", text):
        if EVENTISH.search(sent) and re.search(r"\bappl(?:y|ying|ied|ication)", sent, re.I) and not JOB_WORDS.search(sent):
            return "other", ""
    got = _hit(STARTED, text)
    if got and not ANNOUNCE.search(subject):
        return "started", got.group(0)
    # a page that asks how you know it was received is a FAQ, not a receipt
    faq = any(s.strip().endswith("?") and re.search(r"\bhow (?:do|will|can) i know\b|\bwas (?:it |my application )?received\b|"
                                                     r"\bdid you (?:get|receive)\b", s, re.I)
              for s in re.split(r"(?<=[?.!])\s+", lead))
    got = _hit(RECEIVED, text, conditional=True, about="application")
    if got and not ANNOUNCE.search(subject) and not faq:
        return "application", got.group(0)
    if RECEIVED_SUBJECT.search(subject) and not ANNOUNCE.search(subject) and not EVENTISH.search(subject + " " + lead[:200]):
        return "application", "subject: " + RECEIVED_SUBJECT.search(subject).group(0)
    return "other", ""


def receipt_text(msg):
    """The subject and the sentence that makes the message a receipt (or news):
    where the program it is about is named. Equal-opportunity boilerplate
    ('committed to diversity') doesn't count."""
    subject = _plain(msg.get("subject"))
    lead = _plain(msg.get("body"))[:LEAD]
    text = subject + " | " + lead
    found = [subject]
    for rx in (STATUS, RECEIVED, STARTED):
        for m in rx.finditer(text):
            if m.start() > len(subject):
                found.append(_sentence(text, m))
    found += re.findall(r"\b(?:position|program|job|opportunity|requisition)\s*[:#-]\s*[^.|]{3,80}", lead, re.I)
    return " ".join(x for x in dict.fromkeys(found) if x and not EEO.search(x))


def firm_for(msg, doms=None):
    """(firm, sure). The sender's domain, display name or subject is sure; a
    firm found only in the body is a guess for you to confirm."""
    key = firms.firm_of_email(msg.get("from"), doms)
    if key:
        return key, True
    for text in (msg.get("from_name"), msg.get("subject")):
        key = firms.firm_in_text(_plain(text))
        if key:
            return key, True
    key = firms.firm_in_text(_plain(msg.get("body"))[:1500])
    return key, False


def _cues(text):
    """Tracks the text names. For the 2028 cycle a bare 2027 is not one: 2028
    programs interview in January 2027. 'First-year' is, and so is any '1L'."""
    main, first = settings().tracks
    year = settings().cycle
    tracks = set()
    if re.search(r"\b1Ls?\b|\bfirst[- ]year\b|\bsummer (?:of )?%d\b|\b%d (?:1L|summer)\b" % (year - 1, year - 1), text, re.I):
        tracks.add(first)
    if re.search(r"\b2L\b|\b%d\b|\bsecond[- ]year\b" % year, text, re.I):
        tracks.add(main)
    return tracks, {code for code, rx in OFFICE_CUES if rx.search(text)}


def _special(text):
    out = set()
    for m in SPECIAL.finditer(text or ""):
        w = m.group(1).lower()
        out.add("fellow" if w.startswith("fellow") else "scholar" if w.startswith("scholar") else w)
    return out


def _track(r):
    return A.track_of(r)


def match_app(firm, msg, apps, others, when, kind="application"):
    """(row id, candidate ids) for the application a receipt is about, or ('',
    ids) for you to settle. Candidates are your rows for the firm plus its
    other programs (1L, fellowships). A track or program named in the subject
    or the receipt sentence narrows them, and naming one no row has sends it
    to you; so does a cue that points away from the one application ticked
    around that date. Then the application already sent wins (a second
    receipt is a duplicate), then your own rows before extra programs, then
    the 2L program, unless the text says 1L."""
    mine = [r for r in apps if r.get("firm") == firm]
    have = {r["id"] for r in mine}
    cands = mine + [r for r in others if r.get("firm") == firm and r["id"] not in have]
    if not cands:
        return "", []
    ids = [r["id"] for r in cands]
    for r in cands:
        if r.get("confirm_ref") and r["confirm_ref"] == msg.get("message_id"):
            return r["id"], [r["id"]]
    ticked = [r for r in cands if not r.get("confirmed") and when and store.parse_date(r.get("applied"))
              and abs((store.parse_date(r["applied"]) - when).days) <= 5]
    # a "continue your application" email names the program on its own line
    full = _plain(msg.get("subject")) + " " + _plain(msg.get("body"))[:LEAD]
    if msg.get("program"):      # the reader named the program after reading the email
        named = _plain(msg["program"])
    else:
        named = full if kind == "started" else receipt_text(msg)
    tracks, _ = _cues(named)
    _, offices = _cues(_plain(msg.get("office")) if msg.get("office") else full)
    if len(tracks) == 1:
        # a row also stands for the tracks folded into it (one application per firm)
        folded = {}
        for f in store.read(settings().apps_merged) + store.read(settings().others_merged):
            if f.get("merged_into"):
                folded.setdefault(A.merged_into(f["id"]) or f["merged_into"], set()).add(_track(f))
        cands = [r for r in cands if _track(r) in tracks or tracks & folded.get(r["id"], set())]
        if not cands:
            return "", ids
    words = _special(named)
    if words:
        cands = [r for r in cands if words & _special(r.get("program"))]
        if not cands:
            return "", ids
    else:
        cands = [r for r in cands if not _special(r.get("program"))] or cands
    if offices:
        cands = [r for r in cands if offices & set(re.split(r"[;,/ ]+", r.get("office") or ""))] or cands
    if len(ticked) == 1 and ticked[0] not in cands:
        return "", ids                          # the email points away from what was just sent
    main, first = settings().tracks
    says_1l = first in tracks

    def pick_one(rs):
        if len(rs) > 1 and not says_1l:
            rs = [r for r in rs if _track(r) == main] or rs
        return rs[0] if len(rs) == 1 else None
    sent = [r for r in cands if r.get("applied") or r.get("confirmed")]
    if kind == "started":
        # finished within a few days: that application; otherwise one not sent yet
        done = [r for r in sent if when and store.parse_date(r.get("applied")) and 0 <= (store.parse_date(r["applied"]) - when).days <= 3]
        unsent = [r for r in cands if r not in sent]
        row = pick_one(done) or (pick_one([r for r in unsent if r["id"] in have] or unsent) if unsent else pick_one(sent))
        return (row["id"], ids) if row else ("", ids)
    if sent:
        fresh = [r for r in sent if r in ticked]
        row = pick_one(fresh or [r for r in sent if not r.get("confirmed")] or sent)
        if row is None:
            return "", ids
        # a receipt days after the first one, with unsent programs left, may be a new application
        conf = store.parse_date(row.get("confirmed"))
        if conf and when and (when - conf).days > DUPLICATE_DAYS and len(sent) < len(cands):
            return "", ids
        return row["id"], ids
    row = pick_one([r for r in cands if r["id"] in have] or cands)
    return (row["id"], ids) if row else ("", ids)


def _when(msg):
    """The email's date in the configured timezone, from an ISO stamp or a Date header."""
    d = store.local_dt(msg.get("date"))
    if d is None and msg.get("date"):
        try:
            d = store.local_dt(email.utils.parsedate_to_datetime(str(msg["date"])).isoformat())
        except (TypeError, ValueError, IndexError):
            d = None
    return d.date() if d else None


def ingest(items, today=None):
    """Read saved messages once each; returns [(message_id, kind, result)]."""
    today = today or settings().today()
    doms = firms.domain_map()
    out = []
    with store.ledger_lock():
        log = store.read(settings().confirms)
        seen = {r["message_id"] for r in log}
        apps, others = A.read_apps(), A.read_others()
        changed = False
        # oldest first, so a duplicate receipt finds the application the first one confirmed
        far = datetime.date.max
        for msg in sorted(items, key=lambda m: _when(m) or far):
            mid = str(msg.get("message_id") or msg.get("id") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            # the reader may label each message after reading it; the phrase rules
            # are only a fallback, and on their own they may only confirm an
            # application already ticked
            labeled = msg.get("kind") in KINDS
            kind, evidence = (msg["kind"], "labeled by the reader") if labeled else classify(msg)
            firm, sure = firm_for(msg, doms) if kind != "other" else ("", False)
            when = _when(msg)
            day = min(when or today, today).isoformat()
            rid, cands = match_app(firm, msg, apps, others, when, kind) if firm else ("", [])
            result = "not an application email"
            if kind != "other" and not firm:
                result = "no firm named"
            elif kind != "other" and not sure:
                result = "review: firm only named in the body (%s)" % firm
            elif kind == "application":
                opens = store.parse_date(next((r.get("opens") for r in apps + others if r["id"] == rid), "")) if rid else None
                ticked = bool(rid and next((r for r in apps if r["id"] == rid and r.get("applied")), None))
                if not rid:
                    result = "review: %s" % ("which of %s?" % ", ".join(cands) if cands else "no application row for %s" % firm)
                elif opens and (when or today) < opens and not ticked:
                    result = "review: dated before %s opened (%s) - a sign-up, not an application?" % (rid, opens)
                elif not ticked and not labeled:
                    result = "review: receipt for %s? not ticked - tick it on the tracker if so" % rid
                else:
                    row = A.find_or_adopt(apps, rid, True)
                    bits = []
                    if not row.get("applied"):
                        row["applied"] = day
                        bits.append("applied %s" % day)
                    if not row.get("confirmed"):
                        row["confirmed"], row["confirm_ref"] = day, mid
                        bits.append("confirmed")
                    row["updated"] = today.isoformat()
                    changed = True
                    result = ", ".join(bits) or "already confirmed"
            elif kind == "assessment" and not labeled:
                result = "review: Suited finished%s?" % (" for %s" % rid if rid else "")
            elif kind == "assessment":
                if rid:
                    row = A.find_or_adopt(apps, rid, False)
                    done = checklist_done(row if row else {"checklist": A.other_checks().get(rid, "")})
                    if "suited" not in done:
                        done["suited"] = day
                        if row:
                            row["checklist"] = checklist_str(done)
                            row["updated"] = today.isoformat()
                            changed = True
                        else:
                            side = A.other_checks()
                            side[rid] = checklist_str(done)
                            A.save_other_checks(side)
                        result = "suited done"
                    else:
                        result = "suited already done"
                else:
                    result = "review: Suited finished - for which application?"
            elif kind == "assessment_invite":
                result = "to do: Suited assessment%s" % (" for %s" % rid if rid else "")
            elif kind == "status":
                result = "review: interview or decision news%s" % (" (%s)" % rid if rid else "")
            elif kind == "started":
                result = "started%s" % (" (%s)" % rid if rid else "")
            log.append({"message_id": mid, "date": day if kind != "other" else (when or today).isoformat(),
                        "sender": (msg.get("from") or "")[:80], "subject": _plain(msg.get("subject"))[:120],
                        "kind": kind, "firm": firm, "app_id": rid, "result": result,
                        "evidence": evidence[:80], "logged": today.isoformat(), "resolved": ""})
            out.append((mid, kind, result))
        if changed:
            A.save(apps)
        log.sort(key=lambda r: (r["date"], r["message_id"]))
        store.write(settings().confirms, CONF_COLS, log)
    return out


def needs_eye(today=None):
    """Logged messages to look at: unresolved reviews, Suited invites
    not yet done, and applications started but never sent."""
    today = today or settings().today()
    log = store.read(settings().confirms)
    apps = {r["id"]: r for r in A.read_apps()}
    side = A.other_checks()
    out = []
    for r in log:
        if r["resolved"]:
            continue
        if r["result"].startswith("review"):
            out.append(r)
        elif r["kind"] == "assessment_invite":
            a = apps.get(r["app_id"])
            done = checklist_done(a) if a else checklist_done({"checklist": side.get(r["app_id"], "")})
            if "suited" not in done:
                out.append(r)
        elif r["kind"] == "started" and r["firm"]:
            d = store.parse_date(r["date"])
            if r["app_id"]:
                a = apps.get(r["app_id"])
                went_in = bool(a and (a.get("applied") or a.get("confirmed")))
            else:   # no row named: anything sent to that firm on or after the day it was started
                went_in = any(a["firm"] == r["firm"] and (store.parse_date(a.get("confirmed")) or store.parse_date(a.get("applied"))
                                                          or datetime.date.min) >= (d or datetime.date.min)
                              for a in apps.values())
            if d and not went_in and (today - d).days >= STARTED_GRACE:
                out.append(dict(r, result="started %s, never confirmed - finish or check the portal" % r["date"]))
    return out


def _undo(apps, log_row):
    """Take back what ingest did for one message: the receipt's `confirmed`,
    the `applied` it filled in, a Suited tick."""
    mid = log_row["message_id"]
    for row in list(apps):
        if row.get("confirm_ref") == mid:
            if log_row["result"].startswith("applied ") and row.get("applied") == log_row["result"][8:18]:
                row["applied"] = ""
            row["confirmed"] = row["confirm_ref"] = ""
            A.drop_if_empty(apps, row)
    if log_row["kind"] == "assessment" and log_row["result"] == "suited done" and log_row["app_id"]:
        row = next((r for r in apps if r["id"] == log_row["app_id"]), None)
        if row:
            done = checklist_done(row)
            if done.get("suited") == log_row["date"]:
                done.pop("suited")
                row["checklist"] = checklist_str(done)
        else:
            side = A.other_checks()
            done = checklist_done({"checklist": side.get(log_row["app_id"], "")})
            if done.get("suited") == log_row["date"]:
                done.pop("suited")
                side[log_row["app_id"]] = checklist_str(done)
                A.save_other_checks(side)


def resolve(message_id, target, today=None):
    """Settle one logged message: 'ignore' (and undo anything ingest wrote for
    it), or the application id it belongs to (a receipt then confirms that row
    instead of whatever ingest chose; a Suited one ticks it)."""
    today = today or settings().today()
    with store.ledger_lock():
        log = store.read(settings().confirms)
        r = next((x for x in log if x["message_id"] == message_id), None)
        if r is None:
            raise KeyError(message_id)
        apps = A.read_apps()
        if target != "ignore" and not any(a["id"] == target for a in apps) \
                and not any(o["id"] == target for o in A.read_others()):
            raise ValueError("no application %s" % target)
        if target == "ignore" or target != r["app_id"]:
            _undo(apps, r)
        if target != "ignore":
            row = A.find_or_adopt(apps, target, r["kind"] in ("application", "status"))
            d = min(store.parse_date(r["date"]) or today, today).isoformat()
            if r["kind"] == "assessment":
                src = row if row is not None else {"checklist": A.other_checks().get(target, "")}
                done = checklist_done(src)
                r["result"] = "suited already done" if "suited" in done else "suited done"
                done.setdefault("suited", d)
                if row is None:
                    side = A.other_checks()
                    side[target] = checklist_str(done)
                    A.save_other_checks(side)
                else:
                    row["checklist"] = checklist_str(done)
            elif r["kind"] in ("application", "status") and row is not None:
                # you say this message shows the application went in
                bits = []
                if r["kind"] == "application" and not row.get("applied"):
                    row["applied"] = d
                    bits.append("applied %s" % d)
                if not row.get("confirmed"):
                    row["confirmed"], row["confirm_ref"] = d, message_id
                    bits.append("confirmed")
                r["result"] = ", ".join(bits) or "already confirmed"
            if row is not None:
                row["updated"] = today.isoformat()
            r["app_id"] = target
        A.save(apps)
        r["resolved"] = today.isoformat() + (" ignored" if target == "ignore" else "")
        store.write(settings().confirms, CONF_COLS, log)
    return "%s -> %s" % (message_id, target)


def confirm_since(today=None):
    """Where the next search starts: two days before the last ingest, else
    receipts_since, else FIRST_WINDOW days back."""
    log = store.read(settings().confirms)
    days = [store.parse_date(r["logged"]) for r in log if store.parse_date(r["logged"])]
    if days:
        return max(days) - datetime.timedelta(days=2)
    start = store.parse_date(settings().get("receipts_since"))
    return start or (today or settings().today()) - datetime.timedelta(days=FIRST_WINDOW)


def confirm_queries(since):
    """Gmail searches for receipts, assessments, started applications and
    interview or decision news. Broad on purpose; classify() sorts them.
    Senders in receipt_skip_senders (event platforms, a school's mailing
    lists) are left out."""
    # Some Gmail search front ends match every message for {"a b" "c d"}, for a
    # parenthesised OR group, or for more than about five ORs. A bare
    # `A OR B OR C` of five or fewer next to the filters works; OR binds
    # tighter than the implicit AND.
    skip = "".join(" -from:%s" % d.strip() for d in settings().get("receipt_skip_senders") or [] if d.strip())
    after = "after:%s -in:sent -in:drafts%s" % (since.strftime("%Y/%m/%d"), skip)
    groups = [
        ["application has been received", "application was received", "received your application",
         "received your materials", "submitting your application"],
        ["thank you for applying", "thanks for applying", "thank you for your application", "successfully submitted",
         "confirmation that your application"],
        ["subject:confirmation", 'subject:"summer program application"', 'subject:"career opportunities"',
         'subject:"application received"', 'subject:"your application"'],
        ["Suited assessment", "from:suited.com", "from:wearesuited.com"],
        ["invite you to interview", "invite you to a", "schedule an interview", "screening interview"],
        ["we regret", "pleased to offer", "unable to offer"],
    ]
    return ["%s %s" % (after, " OR ".join(p if ":" in p else '"%s"' % p for p in g)) for g in groups]

