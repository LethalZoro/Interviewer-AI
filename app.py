from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz
import openai
import uuid
import json

app = Flask(__name__)
CORS(app)

openai.api_key = ""

# In-memory session storage (use a database in production)
sessions = {}


def extract_text_from_pdf(file_stream):
    text = ""
    doc = fitz.open(stream=file_stream.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()
    return text


def generate_cv_summary_and_identify_skills(cv_text, job_text):

    if cv_text is not None:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an HR assistant summarizing a CV for interview preparation."},
                {"role": "user", "content": f"Summarize the following CV and identify key skills and expertise areas:\n\n{cv_text}"}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        summary = response.choices[0].message['content'].strip()
    else:
        summary = "No CV provided"
    skills_response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a system identifying the main skills for interview questions."},
            {"role": "user", "content": f"Based on this Job Description:\n\n{job_text}\n\nList main skills."}
        ],
        max_tokens=150,
        temperature=0.7
    )
    skills = skills_response.choices[0].message['content'].strip().splitlines()
    return summary, [s.strip('- ') for s in skills if s.strip()]


def generate_questions_by_skill(skill, job_description):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an HR assistant creating interview questions for a specific skill aligned with a job description."},
                {"role": "user", "content": f"Using the job description:\n\n{job_description}\n\nGenerate a basic, intermediate, and advanced interview question for the skill '{skill}'. Format the questions as a JSON object with keys 'basic', 'intermediate', and 'advanced'."}
            ],
            max_tokens=150,
            temperature=0.7
        )
        questions_text = response.choices[0].message['content'].strip()
        return json.loads(questions_text)
    except:
        return {
            "basic": f"Can you explain your experience with {skill}?",
            "intermediate": f"What challenges have you faced when working with {skill}?",
            "advanced": f"How would you implement {skill} in a complex project?"
        }


def generate_unique_questions(cv_summary, skills, job_description):
    questions = []
    seen_questions = set()

    for skill in skills:
        if len(questions) >= 12:
            break

        skill_questions = generate_questions_by_skill(skill, job_description)
        if skill_questions:
            for level in ['basic', 'intermediate', 'advanced']:
                question_text = skill_questions.get(level, '')

                if isinstance(question_text, str) and question_text.strip() and question_text not in seen_questions:
                    questions.append({
                        "id": str(uuid.uuid4()),  # Add UUID here
                        "skill": skill,
                        "level": level,
                        "question": question_text
                    })
                    seen_questions.add(question_text)

                if len(questions) >= 12:
                    break

    return questions[:12]


# def evaluate_answer(answer, question):
#     evaluation_prompt = f"""Evaluate the following answer based on the question '{question}' generated from the Job Description.
#     Does it align well with the expected answer?
#     Judge the answer strictly and if it is not in the scope of the question rate it lower and say so .
#     Answer: {answer}"""

#     response = openai.ChatCompletion.create(
#         model="gpt-3.5-turbo",
#         messages=[
#             {"role": "system",
#                 "content": "You are an HR assistant providing a score(0-10) at the start and feedback for the candidate's answer."},
#             {"role": "user", "content": evaluation_prompt}
#         ],
#         max_tokens=300,
#         temperature=0.7
#     )
#     return response.choices[0].message['content'].strip()


def evaluate_answer(answer, question):
    evaluation_prompt = f"""Evaluate the following answer based on the question '{question}' generated from the Job Description.
    Does it align well with the expected answer?
    Judge the answer strictly and if it is not in the scope of the question rate it lower and say so.
    Provide the response in JSON format with keys 'score' and 'feedback'.
    Answer: {answer}"""

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system",
                "content": "You are an HR assistant providing a score (0-10) and feedback for the candidate's answer."},
            {"role": "user", "content": evaluation_prompt}
        ],
        max_tokens=300,
        temperature=0.7
    )
    feedback_json = response.choices[0].message['content'].strip()
    print(feedback_json)
    try:
        feedback_data = json.loads(feedback_json)
    except json.JSONDecodeError:
        feedback_data = {
            "score": 0,
            "feedback": "Invalid response format"
        }

    return feedback_data


def format_pre_interview_conditions(conditions):
    if not conditions:
        return "None provided"
    # print(conditions['employment_type'])
    # print(conditions.get('employment_type'))
    employment_type = conditions.get('employment_type')
    conditions = conditions.get('conditions', {})
    if employment_type == 'F':
        freelance_conditions = conditions.get('freelance', {})
        return f"""Freelance: {freelance_conditions.get('availability_percentage', 'N/A')} availability at ${freelance_conditions.get('remote_rate', 'N/A')}/hr (remote) / ${freelance_conditions.get('onsite_rate', 'N/A')}/hr (onsite) \n
    Travel Willingness: {freelance_conditions.get('travel_willingness', 'N/A')}\n
    Other Details: {freelance_conditions.get('other_details', 'N/A')}"""
    elif employment_type == 'T':
        full_time_conditions = conditions.get('full_time', {})
        return f"""Full-time: Starts {full_time_conditions.get('start_date', 'N/A')}, {full_time_conditions.get('work_hours', 'N/A')} hrs/wk, ${full_time_conditions.get('salary_expectations', 'N/A')} salary\n
    Work Location: {full_time_conditions.get('work_location', 'N/A')}\n
    Other Details: {full_time_conditions.get('other_details', 'N/A')}"""
    else:
        print("Invalid employment type")
        return "Invalid employment type"


def generate_overall_summary(answers):
    """
    This function collects all feedback from the answered questions and uses the OpenAI API
    to generate an overall summary of the candidate's performance in the interview.
    """
    feedback_details = ""
    for idx, answer in enumerate(answers, start=1):
        feedback_details += (
            f"Question {idx}: {answer['question']['question']}\n"
            f"Feedback: {answer['feedback']}\n\n"
        )

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system",
             "content": "You are an experienced HR professional who summarizes interview performance."},
            {"role": "user",
             "content": f"""Based on the following feedback for each interview question, 
             provide an overall summary of the candidate's performance.
             Include strengths, weaknesses, and areas for improvement.\n\n{feedback_details}"""}
        ],
        max_tokens=500,
        temperature=0.7
    )
    return response.choices[0].message['content'].strip()


# API Endpoints


@app.route('/api/upload', methods=['POST'])
def upload_pdfs():
    try:
        cv_file = request.files['cv']

        job_file = request.files['job_description']
        # print("cv-file and job-file")
        if cv_file.filename == '' or job_file.filename == '':
            cv_text = None
        else:
            cv_text = extract_text_from_pdf(cv_file)
        if job_file.filename == '':
            return jsonify({'error': 'No job description provided'}), 400
        job_text = extract_text_from_pdf(job_file)
        # print("Text Extracted")
        cv_summary, skills = generate_cv_summary_and_identify_skills(
            cv_text, job_text)

        questions = generate_unique_questions(cv_summary, skills, job_text)
        print("Questions Generated")
        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            'cv_summary': cv_summary,
            'questions': questions,
            'pre_conditions': None,
            'answers': [],
            'current_question': 0,
            'total_score': 0
        }
        # print(sessions[session_id])
        return jsonify({
            'session_id': session_id,
            'cv_summary': cv_summary,
            'skills': skills,
            'questions': questions
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/pre-conditions', methods=['POST'])
def submit_pre_conditions():
    data = request.json
    session_id = data['session_id']
    print(session_id)
    if session_id not in sessions:
        return jsonify({'error': 'Invalid session ID'}), 404

    sessions[session_id]['pre_conditions'] = data
    # print(data)
    # print(data['conditions'])
    # print(format_pre_interview_conditions(data))
    return jsonify({'status': 'success', 'pre_conditions': format_pre_interview_conditions(data)})


@app.route('/api/next-question', methods=['GET'])
def get_question():
    session_id = request.args.get('session_id')
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Invalid session ID'}), 404

    session = sessions[session_id]
    questions = session['questions']
    answers = session['answers']

    # Find the next unanswered question
    next_question = None
    for question in questions:
        # Check if this question has been answered
        is_answered = any(answer['question']['id'] ==
                          question['id'] for answer in answers)
        if not is_answered:
            next_question = question
            break

    if not next_question:
        # All questions have been answered
        return jsonify({'status': 'complete'})

    return jsonify({
        # Current question number (1-based index)
        'current': questions.index(next_question) + 1,
        'total': len(questions),  # Total number of questions
        'question': {
            **next_question,
            'id': next_question['id']  # Explicitly include ID in response
        }
    })


@app.route('/api/answer', methods=['POST'])
def submit_answer():
    data = request.json
    session_id = data['session_id']
    answer = data['answer']
    question_id = data['question_id']  # Get question ID from request

    if session_id not in sessions:
        return jsonify({'error': 'Invalid session ID'}), 404

    session = sessions[session_id]

    # Find the question by ID
    question = next(
        (q for q in session['questions'] if q['id'] == question_id), None)
    if not question:
        return jsonify({'error': 'Invalid question ID'}), 400

    # Evaluate the answer
    feedback_json = evaluate_answer(
        answer,
        question['question']
    )
    feedback = feedback_json['feedback']
    # Simple scoring logic
    score = feedback_json['score']

    # Check if this question was already answered
    existing_answer = next(
        (a for a in session['answers'] if a['question']['id'] == question_id), None)
    if existing_answer:
        # Update existing answer
        existing_answer['answer'] = answer
        existing_answer['feedback'] = feedback
        existing_answer['score'] = score
    else:
        # Add new answer
        session['answers'].append({
            'question': question,
            'answer': answer,
            'feedback': feedback,
            'score': score
        })

    # Recalculate total score
    session['total_score'] = sum(a['score'] for a in session['answers'])

    return jsonify({
        'feedback': feedback,
        'Question': question,
        'score': round(score, 2),
        'total_score': round(session['total_score'], 2)
    })


@app.route('/api/report', methods=['GET'])
def generate_report():
    session_id = request.args.get('session_id')
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Invalid session ID'}), 404

    session = sessions[session_id]
    # if len(session['answers']) < len(session['questions']):
    #     return jsonify({'error': 'Interview not complete'}), 400

    total = session['total_score']
    max_score = len(session['questions'])*10
    percentage = (total / max_score) * 100

    overall_summary = generate_overall_summary(session['answers'])

    report = {
        'pre_conditions': format_pre_interview_conditions(session['pre_conditions']),
        'summary': overall_summary,
        'score': f"{total:.1f}/{max_score} ({percentage:.1f}%)",
        'answers': session['answers']
    }

    return jsonify(report)


if __name__ == '__main__':
    app.run(debug=True)
