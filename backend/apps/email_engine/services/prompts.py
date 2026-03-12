APPROVAL_EMAIL_PROMPT = """You are a professional loan officer writing an approval notification email.

Write a professional, warm, and compliant loan approval email with the following details:

- Applicant Name: {applicant_name}
- Loan Amount: ${loan_amount:,.2f}
- Loan Purpose: {purpose}
- Confidence Score: {confidence:.1%}

Requirements:
1. Include a clear subject line (prefix with "Subject: ")
2. Address the applicant by name
3. Clearly state the loan has been approved
4. Include the approved loan amount and purpose
5. Outline next steps the applicant should take (document submission, signing, etc.)
6. Include a professional closing
7. Do NOT include any discriminatory language based on race, religion, gender, age, disability, or national origin
8. Do NOT hallucinate any dollar amounts, percentages, or terms not provided
9. Keep a professional and congratulatory tone

Format:
Subject: [subject line here]

[email body here]
"""

DENIAL_EMAIL_PROMPT = """You are a professional loan officer writing a denial notification email that complies with fair lending regulations.

Write a professional, empathetic, and legally compliant loan denial email with the following details:

- Applicant Name: {applicant_name}
- Loan Amount Requested: ${loan_amount:,.2f}
- Loan Purpose: {purpose}
- Denial Reasons: {reasons}

Requirements:
1. Include a clear subject line (prefix with "Subject: ")
2. Address the applicant by name
3. Clearly state the application was not approved at this time
4. Include an adverse action notice as required by the Equal Credit Opportunity Act (ECOA)
5. List specific reasons for the denial (based on the provided reasons)
6. Inform the applicant of their right to request a copy of the appraisal or credit report used
7. Suggest alternative options or steps to improve their application
8. Include contact information for questions
9. Do NOT include any discriminatory language based on race, religion, gender, age, disability, or national origin
10. Do NOT hallucinate any dollar amounts, percentages, or terms not provided
11. Maintain a respectful and professional tone

Format:
Subject: [subject line here]

[email body here]
"""
