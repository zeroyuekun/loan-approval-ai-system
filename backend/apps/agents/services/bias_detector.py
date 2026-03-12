import json
import os

import anthropic


class BiasDetector:
    """Analyzes generated emails for potential bias using Claude."""

    BIAS_CATEGORIES = ['gender', 'race', 'age', 'religion', 'disability', 'marital_status']

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))

    def analyze(self, email_text, application_context):
        """
        Analyze email text for potential bias.

        Returns:
            dict with score (0-100), categories, analysis, flagged, requires_human_review
        """
        prompt = f"""Analyze the following loan decision email for potential bias across these categories:
{', '.join(self.BIAS_CATEGORIES)}

Email text:
---
{email_text}
---

Application context:
- Loan Amount: ${application_context.get('loan_amount', 'N/A')}
- Purpose: {application_context.get('purpose', 'N/A')}
- Decision: {application_context.get('decision', 'N/A')}

Score the email from 0-100 where:
- 0-30: No bias detected, passes review
- 31-60: Potential bias detected, flagged for human review
- 61-100: Significant bias detected, should be rejected and regenerated

Respond in JSON format only:
{{
    "score": <number>,
    "categories": [<list of bias categories detected, empty if none>],
    "analysis": "<detailed analysis>"
}}"""

        response = self.client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1024,
            messages=[{'role': 'user', 'content': prompt}],
        )

        response_text = response.content[0].text

        try:
            # Extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            result = json.loads(response_text[json_start:json_end])
        except (json.JSONDecodeError, ValueError):
            result = {
                'score': 0,
                'categories': [],
                'analysis': 'Unable to parse bias analysis response.',
            }

        score = result.get('score', 0)

        return {
            'score': score,
            'categories': result.get('categories', []),
            'analysis': result.get('analysis', ''),
            'flagged': score > 30,
            'requires_human_review': 30 < score <= 60,
        }
