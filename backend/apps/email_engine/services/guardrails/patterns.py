"""Pattern constants used by GuardrailChecker.

Extracted from the original monolithic guardrails.py so the check methods
live in engine.py free of ~370 lines of regex tables. The class attrs on
GuardrailChecker re-export every name here, so `self.PROHIBITED_TERMS`
and `GuardrailChecker.PROHIBITED_TERMS` both still work.
"""

import re

PROHIBITED_TERMS = [
    # Discriminatory language patterns (use non-capturing groups so findall returns the full match)
    re.compile(r"\b(?:race|racial|ethnicity|ethnic)\b", re.IGNORECASE),
    re.compile(r"\b(?:religion|religious|church|mosque|synagogue|temple)\b", re.IGNORECASE),
    re.compile(r"\b(?:gender|sex|male|female|transgender)\b", re.IGNORECASE),
    re.compile(r"\b(?:pregnant|pregnancy|maternity)\b", re.IGNORECASE),
    re.compile(r"\b(?:disability|disabled|handicap)\b", re.IGNORECASE),
    re.compile(r"\b(?:national origin|nationality|immigrant|alien)\b", re.IGNORECASE),
    re.compile(r"\b(?:marital status|married|divorced|widowed)\b", re.IGNORECASE),
    # "single" only triggers when NOT followed by common financial/application nouns
    re.compile(
        r"\bsingle\b(?!\s+(?:\w+\s+)*?(?:payment|applicant|application|account|transaction|loan|source|income|person|borrower|repayment|monthly|amount|point|entry|deposit|product|obligation|contact|reference|instalment|rate|fee|charge|document|step|purpose|entity|item|place|call|email|platform|portal|goal|saver|everyday|savings|option|alternative|offer|phone|number|line|action|digit|click|visit))",
        re.IGNORECASE,
    ),
    # "age" only triggers when NOT in financial/legal contexts
    re.compile(
        r"\bage\b(?!\s*(?:of|action|notice|requirement|pension|bracket|limit|discrimination|act|group|range|related|based|verification|eligibility|threshold))",
        re.IGNORECASE,
    ),
]

AGGRESSIVE_TERMS = [
    re.compile(r"\b(stupid|idiot|foolish|incompetent)\b", re.IGNORECASE),
    re.compile(r"\b(demand|insist|must immediately)\b", re.IGNORECASE),
    re.compile(r"\b(threat|threaten|consequences)\b", re.IGNORECASE),
    re.compile(r"\b(never|always)\s+(will|should|can)\b", re.IGNORECASE),
    re.compile(r"\b(you failed|your fault|blame)\b", re.IGNORECASE),
    re.compile(r"\b(unacceptable|disgraceful|shocking)\b", re.IGNORECASE),
]

# AI-giveaway phrases that real bank officers never use
AI_GIVEAWAY_TERMS = [
    # "pleased to inform" and "pleased to confirm" are legitimate in formal approval letters
    # re.compile(r'\bpleased to (?:inform|advise)\b', re.IGNORECASE),
    re.compile(r"\bdelighted\b", re.IGNORECASE),
    re.compile(r"\bthrilled\b", re.IGNORECASE),
    re.compile(r"\bgreat news\b", re.IGNORECASE),
    re.compile(r"\bexciting\b", re.IGNORECASE),
    re.compile(r"\bwe are happy to\b", re.IGNORECASE),
    re.compile(r"\bI wanted to reach out\b", re.IGNORECASE),
    re.compile(r"\bnavigate\b", re.IGNORECASE),
    # re.compile(r'\bjourney\b', re.IGNORECASE),  # Removed: legitimate in Australian lending ("home ownership journey")
    re.compile(r"\bleverage\b", re.IGNORECASE),
    re.compile(r"\bempower\b", re.IGNORECASE),
    # re.compile(r'\bcomprehensive\b', re.IGNORECASE),  # Removed: legitimate in formal letters ("comprehensive loan agreement")
    re.compile(r"\btailored\b", re.IGNORECASE),
    re.compile(r"\brest assured\b", re.IGNORECASE),
    # re.compile(r'\bdon[\u2019\']t hesitate\b', re.IGNORECASE),  # Removed: legitimate in formal approval/customer-service correspondence
    # re.compile(r'\bwe are here to help\b', re.IGNORECASE),  # Removed: legitimate in hardship/customer-service sections
    # re.compile(r'\bwalk you through\b', re.IGNORECASE),  # Removed: legitimate in formal banking ("walk you through the loan terms")
    re.compile(r"\bevery step of the way\b", re.IGNORECASE),
    re.compile(r"\bwe understand how important\b", re.IGNORECASE),
    re.compile(r"\bwe understand this (?:may be|is) disappointing\b", re.IGNORECASE),
    re.compile(r"\bnot the outcome you were hoping for\b", re.IGNORECASE),
    re.compile(
        r"\bwe (?:understand|know) (?:this|how) (?:is|may be|must be) (?:difficult|hard|tough|frustrating)\b",
        re.IGNORECASE,
    ),
    # Apology / sorry — hard red line: denial letters never apologise or express
    # disappointment (project owner's explicit rule in CLAUDE.md). Enforcing
    # here as a deterministic regex rather than relying on the LLM prompt alone.
    re.compile(r"\bsorry\b", re.IGNORECASE),
    re.compile(r"\bapologis(?:e|es|ing|ed)\b", re.IGNORECASE),
    re.compile(r"\bapologiz(?:e|es|ing|ed)\b", re.IGNORECASE),
    re.compile(r"\bapolog(?:y|ies)\b", re.IGNORECASE),
    re.compile(r"\bdisappointment\b", re.IGNORECASE),
    re.compile(r"\bregret(?:fully|ful|table)?\b", re.IGNORECASE),
    re.compile(r"\bwe want to be transparent about\b", re.IGNORECASE),
    # re.compile(r'\bwe appreciate the trust\b', re.IGNORECASE),  # Removed: legitimate closing in approval letters
    re.compile(r"\bregardless of (?:this|the) outcome\b", re.IGNORECASE),
    re.compile(r"\bshould you have any questions at all\b", re.IGNORECASE),
    # Transitional adverbs (strongest AI-tell)
    re.compile(r"\badditionally\b", re.IGNORECASE),
    re.compile(r"\bfurthermore\b", re.IGNORECASE),
    re.compile(r"\bmoreover\b", re.IGNORECASE),
    re.compile(r"\bin addition\b", re.IGNORECASE),
    re.compile(r"\bconsequently\b", re.IGNORECASE),
    re.compile(r"\bas such\b", re.IGNORECASE),
    re.compile(r"\baccordingly\b", re.IGNORECASE),
    # Hedging qualifiers
    re.compile(r"\bmay potentially\b", re.IGNORECASE),
    re.compile(r"\bcould potentially\b", re.IGNORECASE),
    re.compile(r"\bit is possible that\b", re.IGNORECASE),
    re.compile(r"\bmight be able to\b", re.IGNORECASE),
    # Performative empathy
    re.compile(r"\bwe understand that\b", re.IGNORECASE),
    re.compile(r"\bwe recognise that\b", re.IGNORECASE),
    re.compile(r"\bwe appreciate that\b", re.IGNORECASE),
    # Over-formal constructions
    re.compile(r"\bwe would like to\b", re.IGNORECASE),
    re.compile(r"\bwe would like you to\b", re.IGNORECASE),
    re.compile(r"\bshould you wish to\b", re.IGNORECASE),
    re.compile(r"\bshould you require\b", re.IGNORECASE),
    re.compile(r"\bshould you have any\b", re.IGNORECASE),
    re.compile(r"\bwe wish you\b", re.IGNORECASE),
    # re.compile(r'\bwe are pleased to inform you\b', re.IGNORECASE),  # Removed: industry-standard in AU banking (ANZ, CBA, Westpac all use it)
    re.compile(r"\bwe appreciate your trust in\b", re.IGNORECASE),
    re.compile(r"\bwe truly (?:value|care|appreciate)\b", re.IGNORECASE),
    re.compile(r"\bit is our pleasure to\b", re.IGNORECASE),
    # re.compile(r'\bwe look forward to\b', re.IGNORECASE),  # Removed: legitimate closing in approval letters
    # AI closing/filler patterns
    re.compile(r"\bplease feel free to\b", re.IGNORECASE),
    re.compile(r"\bwe are available\b", re.IGNORECASE),
    re.compile(r"\bthank you for trusting\b", re.IGNORECASE),
    re.compile(r"\bin order to\b", re.IGNORECASE),
    re.compile(r"\bat this point in time\b", re.IGNORECASE),
    re.compile(r"\bit is important to note that\b", re.IGNORECASE),
    re.compile(r"\bit is worth noting that\b", re.IGNORECASE),
    re.compile(r"\bmoving forward\b", re.IGNORECASE),
    re.compile(r"\bgoing forward\b", re.IGNORECASE),
]

# Unprofessional financial language — real banks never use these
# Sources: ASIC RG 234 (misleading/deceptive conduct), NCCP Act s133
UNPROFESSIONAL_FINANCIAL_TERMS = [
    re.compile(r"\bguaranteed approval\b", re.IGNORECASE),
    re.compile(r"\b100% approval\b", re.IGNORECASE),
    re.compile(r"\bno questions asked\b", re.IGNORECASE),
    re.compile(r"\brisk[- ]free\b", re.IGNORECASE),
    re.compile(r"\btoo good to (?:be true|pass up)\b", re.IGNORECASE),
    re.compile(r"\byou deserve\b", re.IGNORECASE),
    re.compile(r"\byou[\u2019\']ve earned\b(?!\s+(?:through|over|with|by|during|in))", re.IGNORECASE),
    # "congratulations" removed: appropriate in formal approval letters
    re.compile(r"\bexclusive(?:ly)? for you\b", re.IGNORECASE),
    re.compile(r"\bbest (?:rate|deal|offer) (?:in|on the) (?:market|australia)\b", re.IGNORECASE),
    re.compile(r"\blowest (?:rate|fee|cost)\b", re.IGNORECASE),
    re.compile(r"\bno (?:hidden |extra )?(?:fees|charges|costs)\b", re.IGNORECASE),
    re.compile(r"\b(?:pre[- ]?approved|already approved)\b", re.IGNORECASE),
    re.compile(r"\blimited (?:time|spots?|availability)\b", re.IGNORECASE),
    re.compile(r"\bdon[\u2019\']t miss (?:out|this)\b", re.IGNORECASE),
]

# Phrases that are factually correct but demeaning in context.
# Each tuple: (pattern, better_alternative, context_note)
DIGNITY_VIOLATIONS = [
    (
        re.compile(r"\byou (?:have |had )?no (?:job|employment|work|income)\b", re.IGNORECASE),
        "your current employment situation",
        "Implies personal failing rather than circumstance",
    ),
    (
        re.compile(r"\byou (?:are|were) unemployed\b", re.IGNORECASE),
        "your employment status at the time of application",
        "Labels the person, not the situation",
    ),
    (
        re.compile(r"\byou lost your job\b", re.IGNORECASE),
        "a change in your employment circumstances",
        "Assigns fault to the customer",
    ),
    (
        re.compile(r"\byou (?:are|were) (?:let go|fired|sacked|terminated|made redundant)\b", re.IGNORECASE),
        "a change in your employment circumstances",
        "Too blunt about job loss",
    ),
    (
        re.compile(r"\byou lack (?:stable |steady )?employment\b", re.IGNORECASE),
        "your employment tenure at the time of application",
        "Implies personal deficiency",
    ),
    (
        re.compile(r"\byou(?:r)? (?:do not|don[\u2019\']t) have a (?:stable |steady |permanent )?job\b", re.IGNORECASE),
        "your current employment arrangement",
        "Implies personal failing",
    ),
    (
        re.compile(r"\byou(?:r income is| earn| make) (?:too little|not enough|insufficient)\b", re.IGNORECASE),
        "the loan amount relative to your verified income",
        "Passes judgment on earning capacity",
    ),
    (
        re.compile(r"\byou cannot afford\b", re.IGNORECASE),
        "the requested amount exceeded our serviceability thresholds",
        "Implies personal inadequacy",
    ),
    (
        re.compile(r"\byou(?:r)? (?:do not|don[\u2019\']t) earn enough\b", re.IGNORECASE),
        "your income relative to the loan amount",
        "Judges the person not the ratio",
    ),
    (
        re.compile(r"\byour (?:poor|bad|low|weak) (?:credit|finances|financial)\b", re.IGNORECASE),
        "your credit profile at the time of assessment",
        "Value judgment on the person",
    ),
    (
        re.compile(r"\byou(?:r)? (?:failed|inability) to (?:pay|repay|meet|manage)\b", re.IGNORECASE),
        "repayment capacity based on our assessment",
        "Implies personal failure",
    ),
    (
        re.compile(r"\byour debt (?:is|was) too (?:high|much|large)\b", re.IGNORECASE),
        "your existing obligations relative to income",
        "Sounds like a personal lecture",
    ),
    (
        re.compile(r"\byou (?:are|were) (?:in |carrying )?too much debt\b", re.IGNORECASE),
        "your debt-to-income ratio",
        "Blames the customer",
    ),
    (
        re.compile(r"\byou(?:r)? (?:have |had )?(?:a )?(?:bad|poor|terrible|awful) credit\b", re.IGNORECASE),
        "your credit history at the time of assessment",
        "Labels the person through their credit",
    ),
    (
        re.compile(r"\byou (?:defaulted|missed payments)\b", re.IGNORECASE),
        "your repayment history as reported by credit bureaus",
        "Accusatory tone",
    ),
    (
        re.compile(r"\byou went bankrupt\b", re.IGNORECASE),
        "a prior bankruptcy event on your credit file",
        "Defines the person by the event",
    ),
    (
        re.compile(r"\byou (?:have |had )?no savings\b", re.IGNORECASE),
        "your savings position at the time of application",
        "Implies irresponsibility",
    ),
    (
        re.compile(r"\byou are too (?:old|young)\b", re.IGNORECASE),
        "the loan term relative to standard lending criteria",
        "Direct age discrimination",
    ),
    (
        re.compile(r"\byou(?:r)? (?:do not|don[\u2019\']t) own (?:a |your )?(?:home|property|house)\b", re.IGNORECASE),
        "your current accommodation arrangements",
        "Implies lesser status for renters",
    ),
    (
        re.compile(r"\byou (?:are|were) (?:not |un)?(?:suitable|eligible|qualified|worthy)\b", re.IGNORECASE),
        "your application did not meet our lending criteria at this time",
        "Labels the person as deficient",
    ),
    (
        re.compile(r"\byou (?:are|were) (?:a |an )?(?:high|greater|elevated) risk\b", re.IGNORECASE),
        "the risk profile of this application",
        "Labels the human as a risk",
    ),
]

# Psychology-informed reframes: (pattern, suggestion, research_basis)
# Sources: Kahneman/Tversky framing effect, Hayne Royal Commission,
# ABA Financial Difficulty Guideline 2025, Banking Code para 7(c),
# Peak-end rule (Kahneman), dual-process theory (System 1/2)
PSYCHOLOGY_REFRAMES = {
    "negative_framing": [
        (
            re.compile(r"\bwe cannot (?:offer|provide|approve|give|extend|grant)\b", re.IGNORECASE),
            'reframe around what you CAN do: "what we can offer is..."',
            "Framing effect: gain-framed language improves perception by 15-30%",
        ),
        (
            re.compile(r"\byou are unable to\b", re.IGNORECASE),
            'reframe as situational: "your application at this time"',
            "Framing effect: attribute to situation, not the person",
        ),
        (
            re.compile(r"\bthis is not possible\b", re.IGNORECASE),
            '"what is possible is..." or "an option available to you is..."',
            "Positive reframing converts constraints into alternatives",
        ),
        (
            re.compile(r"\bthere is no (?:way|option|possibility)\b", re.IGNORECASE),
            '"the options available to you include..."',
            "Loss aversion: finality triggers 2x the emotional pain",
        ),
    ],
    "institutional_coldness": [
        (
            re.compile(r"\bthe bank has (?:determined|decided|concluded)\b", re.IGNORECASE),
            'use first person: "I\'ve reviewed..." or "after looking at your details..."',
            "Hayne Commission: institutional voice creates power imbalance",
        ),
        (
            re.compile(r"\bour systems? (?:indicate|show|flag|record)\b", re.IGNORECASE),
            '"when I reviewed your application..."',
            "Monzo: active voice always; never hide behind systems",
        ),
        (
            re.compile(r"\b(?:per|as per) our (?:policy|policies|records|guidelines)\b", re.IGNORECASE),
            'explain the reason directly: "because..." or "the reason is..."',
            "Banking Code para 7(c): treat with sensitivity, respect and compassion",
        ),
        (
            re.compile(r"\bit has been determined (?:that|by)\b", re.IGNORECASE),
            '"I\'ve found that..." or "after reviewing your application..."',
            "Passive voice hides accountability; active voice builds trust",
        ),
    ],
    "finality_language": [
        (
            re.compile(r"\bthis decision is final\b", re.IGNORECASE),
            '"this decision is based on your circumstances at the time of application"',
            'ABA Guideline 2025: frame as "not yet", not permanent rejection',
        ),
        (
            re.compile(r"\bthere is nothing (?:more|else|further) we can do\b", re.IGNORECASE),
            '"if your circumstances change, please reach out"',
            "Loss aversion: finality doubles emotional impact",
        ),
        (
            re.compile(r"\bwe have closed your\b", re.IGNORECASE),
            "describe what happens next rather than what has ended",
            "Peak-end rule: the final message determines the lasting memory",
        ),
        (
            re.compile(r"\bno further action (?:will be|is|can be) taken\b", re.IGNORECASE),
            '"if you\'d like to discuss this further..."',
            "Credit union research: supportive denials increase future loyalty",
        ),
        (
            re.compile(r"\bthis matter is (?:closed|concluded|finalised)\b", re.IGNORECASE),
            "end with forward-looking language and a direct contact",
            "Banking Code para 172: respond promptly to requests to discuss difficulties",
        ),
    ],
    "weak_closings": [
        (
            re.compile(r"\bwe wish you (?:well|all the best|good luck|the best)\b", re.IGNORECASE),
            "use specific warmth: \"Thanks for coming to us, [Name]. We'd love to help you find the right option when you're ready.\"",
            "Peak-end rule: generic well-wishes feel dismissive",
        ),
        (
            re.compile(r"\bgood luck (?:with|in|for)\b", re.IGNORECASE),
            "\"if you'd like to explore other options, I'm here to help\"",
            "Recency effect: final sentences determine overall satisfaction",
        ),
    ],
}

# Grammar patterns that undermine professionalism in formal banking correspondence
# Source: Australian Style Manual
GRAMMAR_ISSUES = [
    (re.compile(r"\bcan[\u2019']t\b", re.IGNORECASE), "cannot"),
    (re.compile(r"\bwon[\u2019']t\b", re.IGNORECASE), "will not"),
    (re.compile(r"\bshouldn[\u2019']t\b", re.IGNORECASE), "should not"),
    (re.compile(r"\bcouldn[\u2019']t\b", re.IGNORECASE), "could not"),
    (re.compile(r"\bwouldn[\u2019']t\b", re.IGNORECASE), "would not"),
    (re.compile(r"\bhaven[\u2019']t\b", re.IGNORECASE), "have not"),
    (re.compile(r"\bhasn[\u2019']t\b", re.IGNORECASE), "has not"),
    (re.compile(r"\baren[\u2019']t\b", re.IGNORECASE), "are not"),
    (re.compile(r"\bwasn[\u2019']t\b", re.IGNORECASE), "was not"),
    (re.compile(r"\bweren[\u2019']t\b", re.IGNORECASE), "were not"),
    # Note: "don't", "isn't", "it's", "we'd", "you'll", "we're", "I'm" excluded
    # intentionally — our tone calibration uses these for warmth.
]

# Comparison rate warning — mandatory under National Credit Code Reg 99
COMPARISON_RATE_WARNING_REQUIRED = re.compile(
    r"comparison rate.*?applies only to the example",
    re.IGNORECASE | re.DOTALL,
)

# Australian legal disclosures are required — strip them before checking for prohibited terms
COMPLIANCE_DISCLOSURE_PATTERN = re.compile(
    r"(?:"
    r"the equal credit opportunity act prohibits"
    r"|under australian law"
    r"|under the .{0,120}(?:privacy act|nccp act|national consumer credit|human rights|discrimination act|banking code|consumer law)"
    r"|(?:sex|racial|disability|age) discrimination act\s*\d*"
    r"|australian human rights commission act"
    r"|responsible lending (?:obligations|assessment|conduct)"
    r"|banking code of practice"
    r"|national consumer credit protection act"
    r"|afca|australian financial complaints authority"
    r"|equifax|illion|experian"
    r"|asic|australian securities and investments commission"
    r"|credit report(?:ing)?"
    r"|hayne royal commission"
    r"|anti[- ]money laundering"
    r").*?(?:\.|$)",
    re.IGNORECASE | re.DOTALL,
)

# Marketing-specific AI-giveaway terms — more permissive than the decision
# email list because product descriptions legitimately use "comprehensive"
# and "tailored", and customer follow-ups use "don't hesitate".
MARKETING_AI_GIVEAWAY_TERMS = [
    re.compile(r"\bpleased to (?:confirm|inform|advise)\b", re.IGNORECASE),
    re.compile(r"\bdelighted\b", re.IGNORECASE),
    re.compile(r"\bthrilled\b", re.IGNORECASE),
    re.compile(r"\bgreat news\b", re.IGNORECASE),
    re.compile(r"\bexciting\b", re.IGNORECASE),
    re.compile(r"\bwe are happy to\b", re.IGNORECASE),
    re.compile(r"\bnavigate\b", re.IGNORECASE),
    re.compile(r"\bjourney\b", re.IGNORECASE),
    re.compile(r"\bleverage\b", re.IGNORECASE),
    re.compile(r"\bempower\b", re.IGNORECASE),
    re.compile(r"\brest assured\b", re.IGNORECASE),
    re.compile(r"\bevery step of the way\b", re.IGNORECASE),
    re.compile(r"\bwe understand how important\b", re.IGNORECASE),
    re.compile(r"\bwe understand this (?:may be|is) disappointing\b", re.IGNORECASE),
    re.compile(r"\bnot the outcome you were hoping for\b", re.IGNORECASE),
    re.compile(r"\bnot what you (?:were hoping|wanted|expected)\b", re.IGNORECASE),
    # Apology / sorry — mirrors AI_GIVEAWAY_TERMS. Marketing emails never
    # apologise for the preceding denial; this would re-raise the negative
    # moment and contradicts the peak-end rule.
    re.compile(r"\bsorry\b", re.IGNORECASE),
    re.compile(r"\bapologis(?:e|es|ing|ed)\b", re.IGNORECASE),
    re.compile(r"\bapologiz(?:e|es|ing|ed)\b", re.IGNORECASE),
    re.compile(r"\bapolog(?:y|ies)\b", re.IGNORECASE),
    re.compile(r"\bdisappointment\b", re.IGNORECASE),
    re.compile(r"\bregret(?:fully|ful|table)?\b", re.IGNORECASE),
    re.compile(r"\bwe value you as a customer\b", re.IGNORECASE),
    re.compile(r"\bwe (?:truly|genuinely) (?:want|care|value)\b", re.IGNORECASE),
    re.compile(r"\bwe are pleased to inform you\b", re.IGNORECASE),
    re.compile(r"\bwe want to be transparent about\b", re.IGNORECASE),
    re.compile(r"\bregardless of (?:this|the) outcome\b", re.IGNORECASE),
    re.compile(r"\bshould you have any questions at all\b", re.IGNORECASE),
    re.compile(r"\badditionally\b", re.IGNORECASE),
    re.compile(r"\bfurthermore\b", re.IGNORECASE),
    re.compile(r"\bmoreover\b", re.IGNORECASE),
    re.compile(r"\bin addition\b", re.IGNORECASE),
    re.compile(r"\bconsequently\b", re.IGNORECASE),
    re.compile(r"\bas such\b", re.IGNORECASE),
    re.compile(r"\baccordingly\b", re.IGNORECASE),
    re.compile(r"\bmay potentially\b", re.IGNORECASE),
    re.compile(r"\bcould potentially\b", re.IGNORECASE),
    re.compile(r"\bit is possible that\b", re.IGNORECASE),
    re.compile(r"\bmight be able to\b", re.IGNORECASE),
    re.compile(r"\bwe understand that\b", re.IGNORECASE),
    re.compile(r"\bwe recognise that\b", re.IGNORECASE),
    re.compile(r"\bwe would like to\b", re.IGNORECASE),
    re.compile(r"\bwe would like you to\b", re.IGNORECASE),
    re.compile(r"\bshould you wish to\b", re.IGNORECASE),
    re.compile(r"\bshould you require\b", re.IGNORECASE),
    re.compile(r"\bshould you have any\b", re.IGNORECASE),
    re.compile(r"\bwe wish you\b", re.IGNORECASE),
    re.compile(r"\bplease feel free to\b", re.IGNORECASE),
    re.compile(r"\bwe are committed to\b", re.IGNORECASE),
    re.compile(r"\bwe remain committed to\b", re.IGNORECASE),
    re.compile(r"\bwe are available\b", re.IGNORECASE),
    re.compile(r"\bthank you for choosing\b", re.IGNORECASE),
    re.compile(r"\bthank you for trusting\b", re.IGNORECASE),
    re.compile(r"\bin order to\b", re.IGNORECASE),
    re.compile(r"\bat this point in time\b", re.IGNORECASE),
    re.compile(r"\bit is important to note that\b", re.IGNORECASE),
    re.compile(r"\bit is worth noting that\b", re.IGNORECASE),
    re.compile(r"\bmoving forward\b", re.IGNORECASE),
    re.compile(r"\bgoing forward\b", re.IGNORECASE),
]
