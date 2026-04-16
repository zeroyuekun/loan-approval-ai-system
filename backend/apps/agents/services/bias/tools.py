# ---------------------------------------------------------------------------
# Tool definitions for structured output via tool_use
# ---------------------------------------------------------------------------

BIAS_ANALYSIS_TOOL = {
    "name": "record_bias_analysis",
    "description": "Record the bias analysis results for this email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "categories": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["gender", "race", "age", "religion", "disability", "marital_status"],
                },
            },
            "analysis": {"type": "string"},
        },
        "required": ["score", "categories", "analysis"],
    },
}

EMAIL_REVIEW_TOOL = {
    "name": "record_review_decision",
    "description": "Record the senior compliance review decision.",
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reasoning": {"type": "string"},
        },
        "required": ["approved", "confidence", "reasoning"],
    },
}

MARKETING_BIAS_TOOL = {
    "name": "record_marketing_bias_analysis",
    "description": "Record the marketing email bias analysis results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "categories": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "patronising_tone",
                        "pressure_tactics",
                        "discriminatory_product_steering",
                        "false_promises",
                        "gender",
                        "race",
                        "age",
                        "religion",
                        "disability",
                        "marital_status",
                    ],
                },
            },
            "analysis": {"type": "string"},
        },
        "required": ["score", "categories", "analysis"],
    },
}

MARKETING_REVIEW_TOOL = {
    "name": "record_marketing_review_decision",
    "description": "Record the senior compliance review decision for marketing email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reasoning": {"type": "string"},
        },
        "required": ["approved", "confidence", "reasoning"],
    },
}
