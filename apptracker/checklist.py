"""Materials checklists: what a firm asks for, one item per thing to gather.

A hand-set `needs` column ("resume;cover_letter:opt;law_transcript:later")
wins; otherwise the list is read from the free-text `materials` note, plus the
`letter_required` column. Levels: req (needed to apply), later (can follow,
e.g. once first-semester grades post), opt (welcome, not needed), unknown (the
firm hasn't said; kept only for the cover letter, where guessing wrong costs
an application). Done items live in the `checklist` column as item=date;...
"""

import re
import sys

CHECK_ITEMS = [("resume", "Resume"), ("cover_letter", "Cover letter"),
               ("undergrad", "Undergrad transcript"), ("law_transcript", "Law transcript"),
               ("writing_sample", "Writing sample"), ("statement", "Statement of interest"),
               ("references", "References"), ("suited", "Suited assessment"),
               ("test_score", "LSAT/GRE score"), ("video", "Video intro")]
CHECK_KEYS = [k for k, _ in CHECK_ITEMS]
CHECK_LEVELS = ("req", "later", "opt", "unknown")
_MENTION = [("resume", re.compile(r"\br[eé]sum[eé]s?\b|\bcv\b", re.I)),
            ("cover_letter", re.compile(r"\bcover[- ]letters?\b", re.I)),
            ("writing_sample", re.compile(r"\bwriting samples?\b", re.I)),
            ("statement", re.compile(r"\b(?:personal|written|diversity|interest|short|brief|\d+[- ]word)\s+statements?\b|"
                                     r"\bstatements? of (?:interest|purpose)\b|\bessays?\b|"
                                     r"(?<!firm's )(?<!its )(?<!our )\bstatement\b(?=[^.;]{0,30}\b(?:words?|page|interest)\b)", re.I)),
            ("references", re.compile(r"(?<!for )(?<!should )(?<!must )(?<!to )\breferences?\b(?!\s+(?:the|your|a|an|number|no\.?|id|to|are not|code|specific)\b)|\breference list\b|"
                                       r"\bletters? of (?:recommendation|reference)\b|\brecommendation letters?\b|\brecommenders?\b|"
                                       r"\brecommendations\b", re.I)),
            ("suited", re.compile(r"(?<!best )(?<!better )(?<!well )(?<!most )(?<!ideally )\bsuited\b|\bassessments?\b", re.I)),
            ("test_score", re.compile(r"\b(?:lsat|gre)\b", re.I)),
            ("video", re.compile(r"\bvideo\b", re.I)),
            ("law_transcript", re.compile(r"\b(?:first|1st)[- ](?:semester|term)\b[^.;]{0,30}?\bgrades\b|"
                                          r"\b(?:fall|1L|law school)\b[^.;]{0,15}?\bgrades\b|\bgrades\b", re.I))]
_TRANSCRIPT = re.compile(r"\btranscripts?\b", re.I)
_SEPARATOR = re.compile(r"^(?:[\s,/&()\-]|\b(?:and|or|nor|plus|eg|ie|such as|like|including|type|a|an|the|"
                        r"your|list of|other|another|any|similar)\b)*$", re.I)
_JOIN = re.compile(r",|\b(?:and|or|nor|plus)\b", re.I)
# "X, Y and Z may be submitted later": words after a list that start with a verb
# describe every item in it; "X and Y, Z as a supplement" describes only Z
_PREDICATE = re.compile(r"^[\s(),]*(?:but\s+)?(?:(?:requirements?|materials?|both|each|all|too|also|this)\s+)?"
                        r"(?:may|can|must|should|are|is|will|to be|need|needs|not|aren't|isn't|optional|required|encouraged|welcome)\b", re.I)
_UNKNOWN = re.compile(r"\b(?:unconfirmed|unknown|whether|unclear|not (?:yet )?(?:stated|posted|confirmed)|"
                      r"does not say|doesn't say)\b", re.I)
_OPTIONAL = re.compile(r"\b(?:optional|welcome|encourag\w*|if any|not required,? but|accepted as (?:a )?placeholder|"
                       r"if you have one)\b", re.I)
_NEG_BEFORE = re.compile(r"\b(?:no|neither|nor|without|not|in place of|instead of)\b", re.I)
_NEG_AFTER = re.compile(r"\b(?:not (?:mentioned|listed|required|needed|necessary)|(?:is|are)n't (?:required|needed)|"
                        r"only (?:for|needed for|if|required for)|needed only|"
                        r"for (?:IP|patent)\b[\w ]{0,30}?(?:candidates|applicants|roles|programs?|litigation)|"
                        r"for\b[^.;]{0,40}\bonly\b|"
                        r"(?:dropped|discontinued|eliminated|removed|waived)\b|(?:requirement|it) (?:was|has been) dropped|"
                        r"drop(?:s|ped)? (?:that|the|this) requirement|no longer (?:required|needed|asked|part of|requires?|asks? for))", re.I)
# "once available" or "after grades post" means later; "when applying", "once you
# start" and "as soon as possible" don't
_LATER = re.compile(r"\b(?:(?:once|when|after|as soon as|until)\b(?!\s+possible)(?!\s+(?:you )?apply)(?!\s+you start)"
                    r"[^.;]{0,30}?\b(?:available|released|post(?:s|ed)?|out|grades|final|ready|received|issued)\b|"
                    r"later|to follow|can follow|may follow|supplement\w*|be added|if available|"
                    r"at (?:the )?(?:interview|callback|offer)(?: stage)?|(?:interview|callback|offer) stage|"
                    r"at callbacks?|upon request|if requested|on request)\b", re.I)
# grades before the firm will look: tied to the transcript or grades words, not
# anywhere in the sentence ("complete the Suited assessment before applying")
_GRADES_FIRST = re.compile(
    r"(?:transcripts?|grades)[^.;]{0,30}?\b(?:required before (?:applying|you apply|submitting|an application)|"
    r"before (?:applying|you apply)|(?:are|is) (?:released|posted|available|uploaded) before)|"
    r"\bcomplete (?:first-(?:semester|term)|1L(?: year)?|first-year|full[- ]year)\b[^.;]{0,20}(?:transcript|grades)|"
    r"\bfull 1L transcript\b|\b(?:first )?full[- ]year transcript\b|"
    r"\btranscript with all first[- ]year grades\b|only after it is uploaded|only to students who have uploaded|"
    r"\b(?:apply|applications? (?:are )?(?:reviewed|accepted|considered)) (?:only )?(?:once|after|until) [^.;]{0,40}(?:transcript|grades)|"
    r"\b(?:do not|don't) apply until [^.;]{0,40}(?:transcript|grades)|"
    r"\b(?:application|file) (?:is )?(?:not )?complete (?:once|until|when) [^.;]{0,40}transcript", re.I)
_UNSURE = re.compile(r"\b(?:not (?:yet )?(?:posted|listed|stated|confirmed)|unconfirmed|unknown|"
                     r"last cycle(?:'s)?[^.;]{0,40}(?:asked|required|listed|posting|packet|process|:)|^last cycle\b|"
                     r"\b20(?:1\d|2[0-5])\b[^.;]{0,15}(?:cycle|flyer|posting|brochure|application)|\bunverified\b|"
                     r"search-indexed|third-party|returned 403|lists? (?:no materials|none)\b|check (?:them|it|the portal))", re.I | re.M)


def _mentions(clause):
    """[(start, end, item)] for every checklist item a clause names, in order.
    A bare 'transcript' means the law transcript (what a 1L application waits
    on); 'undergraduate and law school transcripts' names both."""
    found = []
    for key, rx in _MENTION:
        found += [(m.start(), m.end(), key) for m in rx.finditer(clause)]
    prev = 0
    for m in _TRANSCRIPT.finditer(clause):
        lo = max(prev, m.start() - 45)
        back = clause[lo:m.start()].lower()
        # the mention starts at its first qualifier, so "(if any)" inside
        # "undergraduate and graduate (if any) transcripts" is part of the name
        ug, law, grad = back.find("undergrad"), re.search(r"\blaw\b", back), re.search(r"\bgraduate\b", back)
        if ug >= 0:
            found.append((lo + ug, m.end(), "undergrad"))
        if law or (ug < 0 and not grad):
            found.append((lo + law.start() if law else m.start(), m.end(), "law_transcript"))
        elif grad and ug < 0:
            found.append((lo + grad.start(), m.end(), "_grad"))   # a graduate degree's transcript: not asked of a 1L
        prev = m.end()
    # "undergrad/grad grades", "transcripts for all degrees" name the undergraduate record too
    for m in re.finditer(r"\bundergrad(?:uate)?\b[^.;]{0,15}\bgrades\b|\btranscripts? for all degrees\b", clause, re.I):
        found.append((m.start(), m.end(), "undergrad"))
    found = sorted(set(found))
    # one item named in two words ("Suited assessment", "LSAT or GRE") is one mention,
    # so a hedge in front of it reaches all of it
    merged = []
    for f in found:
        if merged and merged[-1][2] == f[2] and re.match(r"^[\s\-/]*(?:or|type|and)?[\s\-/]*$", clause[merged[-1][1]:f[0]] or " "):
            merged[-1] = (merged[-1][0], max(merged[-1][1], f[1]), f[2])
        elif merged and merged[-1][2] == f[2] and f[0] < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], f[1]), f[2])
        else:
            merged.append(f)
    return merged


def _head_level(head):
    # only the words just before a list qualify it: "not yet confirmed for
    # 2028: cover letter, resume" still lists a cover letter and a resume
    pre, colon, post = head.rpartition(":")
    label = bool(colon) and not post.strip()     # "Optional: writing sample" labels the list...
    head = (pre if label else post if colon else head)[-60:]
    if not label and (_UNKNOWN.search(head) or re.search(r"\bif\b[^.;,]{0,40}$", head, re.I)):
        return "unknown"
    if _OPTIONAL.search(head):
        return "opt"
    if _NEG_BEFORE.search(head) and not (label and _UNKNOWN.search(head)):
        return "none"
    return None


_ONLY_SCOPE = re.compile(r"\([^)]*\bonly\)", re.I)


def _tail_level(tail):
    if _ONLY_SCOPE.search(tail):
        return "none"
    if _UNKNOWN.search(tail):
        return "unknown"
    if _OPTIONAL.search(tail):
        return "opt"
    if _NEG_AFTER.search(tail):
        return "none"
    if _LATER.search(tail):
        return "later"
    return None


def _pick(levels):
    for lv in ("unknown", "opt", "none", "later"):
        if lv in levels:
            return lv
    return "req"


def parse_materials(text):
    """{item: level} from a materials note. Items in a list ('X, Y, and Z may
    follow later') share the words after the list; a negation before a list
    ('No writing sample or assessment') covers all of it."""
    text = re.sub(r"\b(e\.g|i\.e|U\.S|etc)\.", lambda m: m.group(1).replace(".", ""), text or "", flags=re.I)
    if _clipped(text):   # the note was cut mid-word: finish a known word, else drop it
        head, _, last = text.rstrip().rpartition(" ")
        full = next((w for w in ("transcripts", "transcript", "assessment", "statement", "references", "letter", "sample")
                     if len(last) >= 5 and w.startswith(last.lower())), "")
        text = head + (" " + full if full else "")
    seen = {}
    for clause in re.split(r"[.;](?=\s|$)", text):
        ms = _mentions(clause)
        runs, run = [], []
        for i, m in enumerate(ms):
            if run and (m[0] < run[-1][1] or _SEPARATOR.match(clause[run[-1][1]:m[0]])):
                run.append(m)
            else:
                if run:
                    runs.append(run)
                run = [m]
        if run:
            runs.append(run)
        head = clause[:runs[0][0][0]] if runs else ""
        for j, run in enumerate(runs):
            gap = clause[run[-1][1]:runs[j + 1][0][0]] if j + 1 < len(runs) else clause[run[-1][1]:]
            # the words in a gap up to its last comma or "and" close this run;
            # the rest opens the next ("..., and an optional video")
            joins = list(_JOIN.finditer(gap)) if j + 1 < len(runs) else []
            cut = joins[-1].start() if joins else len(gap)
            # with no comma or "and", only words after a "but" carry over
            # with no comma or "and", only words from a "(", a dash, a "but" or an
            # "in place of" on carry over
            carry = re.search(r"(?:\(|\s[-\u2013\u2014]\s|\bbut\b|\bin place of\b|\binstead of\b|\brather than\b|"
                              r"\bwithout\b)(?:(?!\(|\s[-\u2013\u2014]\s|\bbut\b).)*$", gap)
            tail, next_head = gap[:cut], (gap[cut:] if joins else carry.group(0) if carry else "")
            hl, tl = _head_level(head), _tail_level(tail)
            whole = bool(_PREDICATE.match(tail))
            label = bool(re.search(r":\s*$", head))      # "Optional: writing sample, references"
            both = bool(re.match(r"^[\s(),]*both\b", tail, re.I))
            # "optional writing sample or video": items chained to the first by a
            # bare or/and (no comma) share its hedge; "optional A, B" does not
            joined = [False] * len(run)
            for k in range(1, len(run)):
                bare = re.match(r"^\s*(?:or|and)\s+(?:a |an |the )?$", clause[run[k - 1][1]:run[k][0]], re.I)
                joined[k] = bool(bare) and (k == 1 or joined[k - 1])
                if not joined[k]:
                    break
            for i, (_, _, key) in enumerate(run):
                # "optional undergraduate transcript, Suited assessment": a hedge
                # in front qualifies its own item; a negation covers the list
                own = hl if hl in ("none", "unknown") or i == 0 or label or joined[i] else None
                reach = whole and not both or i == len(run) - 1 or (both and i >= len(run) - 2)
                levels = [own] + ([tl] if reach else [])
                seen.setdefault(key, []).append(_pick([lv for lv in levels if lv]))
            head = next_head
    seen.pop("_grad", None)
    out = {}
    for key, levels in seen.items():
        pos = [lv for lv in levels if lv in ("req", "later", "opt")]
        if pos:
            out[key] = "later" if "later" in pos else ("req" if "req" in pos else "opt")
        else:
            out[key] = "unknown" if "unknown" in levels else "none"
    return out


_LEVEL_WORDS = {"req": "req", "required": "req", "yes": "req", "y": "req", "": "req", "later": "later",
                "opt": "opt", "optional": "opt", "unknown": "unknown", "?": "unknown", "check": "unknown",
                "none": "none", "no": "none", "n": "none"}


def _clipped(text):
    """Notes scraped from career pages are often stored cut at 240 characters."""
    t = (text or "").rstrip()
    return len(t) >= 239 and not t.endswith((".", ")", ";", "!", "?", '"', "'"))


_KEY_WORDS = {"cover_letter": "cover_letter", "letter": "cover_letter", "transcript": "law_transcript",
              "law_school_transcript": "law_transcript", "undergrad_transcript": "undergrad",
              "undergraduate_transcript": "undergrad", "undergraduate": "undergrad", "writing_sample": "writing_sample",
              "personal_statement": "statement", "statement_of_interest": "statement", "reference": "references",
              "lsat": "test_score", "gre": "test_score", "lsat_score": "test_score", "gre_score": "test_score",
              "suited_assessment": "suited", "cv": "resume", "video_intro": "video", "video_introduction": "video",
              "letters_of_recommendation": "references", "letter_of_recommendation": "references",
              "law_school_transcripts": "law_transcript", "transcripts": "law_transcript"}


def _parse_needs(s):
    """{item: level} from a hand-set list. Case and spaces don't matter;
    'optional' means opt and 'none' drops the item. An unreadable level is
    kept as 'unknown' rather than guessed as required."""
    out = {}
    for part in re.split(r"[;,]", s or ""):
        key, _, lv = part.partition(":")
        key = key.strip().lower().replace("é", "e")
        key = re.sub(r"[\s\-]+", "_", key)
        key = _KEY_WORDS.get(key, _KEY_WORDS.get(key[:-1], key[:-1]) if key.endswith("s") and key not in CHECK_KEYS
                             and key[:-1] in set(CHECK_KEYS) | set(_KEY_WORDS) else key)
        lv = re.sub(r"[.!]+$", "", lv.strip().lower())
        if key in CHECK_KEYS:
            lv = "none" if lv in ("not required", "not needed", "n/a", "na") else _LEVEL_WORDS.get(lv, "unknown")
            if lv != "none":
                out[key] = lv
        elif key:
            sys.stderr.write("needs: ignoring %r (items: %s)\n" % (part.strip(), ", ".join(CHECK_KEYS)))
    return out


def checklist_needs(a):
    """[(item, level)] for one application, in CHECK_ITEMS order. Every firm
    wants a resume and, sooner or later, first-semester grades."""
    if (a.get("needs") or "").strip():
        got = _parse_needs(a["needs"])
    else:
        got = {k: v for k, v in parse_materials(a.get("materials")).items() if v != "none"}
        got["resume"] = "req"
        # no 1L has grades when portals open, so a law transcript follows later
        # unless the firm wants grades before it will look at the application
        about_grades = [c for c in re.split(r"[.;](?=\s|$)", a.get("materials") or "")
                        if re.search(r"transcript|grades", c, re.I)
                        and not re.search(r"\b(?:not (?:required|needed|necessary)|no need|(?:do not|don't|doesn't|does not) "
                                          r"(?:need|have) to|need not|can (?:upload|add|send)|may (?:upload|add|send|apply))\b", c, re.I)]
        if got.get("law_transcript") != "req" or not any(_GRADES_FIRST.search(c) for c in about_grades):
            got["law_transcript"] = "later"
        lr = (a.get("letter_required") or "?").lower()
        if lr in ("y", "yes"):
            got["cover_letter"] = "req"
        elif lr == "optional":
            got["cover_letter"] = "opt"
        elif lr in ("n", "no"):
            got.pop("cover_letter", None)
        elif got.get("cover_letter") not in ("req", "opt", "later"):
            got["cover_letter"] = "unknown"
        got = {k: v for k, v in got.items() if v != "unknown" or k == "cover_letter"}
    return [(k, got[k]) for k in CHECK_KEYS if k in got]


def needs_str(a):
    return ";".join(k if lv == "req" else "%s:%s" % (k, lv) for k, lv in checklist_needs(a))


def materials_unsure(a):
    """True when the materials note is a guess (last cycle's list, a page that
    lists nothing, a portal not yet seen)."""
    return not (a.get("needs") or "").strip() and bool(_UNSURE.search(a.get("materials") or ""))


def checklist_done(a):
    """{item: date} from the `checklist` column."""
    out = {}
    for part in (a.get("checklist") or "").split(";"):
        key, _, d = part.strip().partition("=")
        if key in CHECK_KEYS and d:
            out[key] = d
    return out


def checklist_str(done):
    return ";".join("%s=%s" % (k, done[k]) for k in CHECK_KEYS if done.get(k))
