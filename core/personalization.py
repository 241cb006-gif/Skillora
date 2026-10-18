import os

COLLEGE_NAME = os.getenv('COLLEGE_NAME', 'Sri Ramakrishna College of Arts and Science for Women')
COLLEGE_LOGO = os.getenv('COLLEGE_LOGO', '')
COLLEGE_WEBSITE_URL = os.getenv('COLLEGE_WEBSITE_URL', 'https://srcw.ac.in/')
FACULTY_COORDINATOR = os.getenv('FACULTY_COORDINATOR', 'Faculty Coordinator Name')
COLLEGE_CONTACT = os.getenv('COLLEGE_CONTACT', '')
ABOUT_SKILLORA = os.getenv(
    'ABOUT_SKILLORA',
    'Skillora helps students share skills, discover learning opportunities, and grow through structured learning experiences approved by the college.'
)
STUDENT_NAME_PLACEHOLDER = os.getenv('STUDENT_NAME_PLACEHOLDER', 'Student Name')
STUDENT_DEPARTMENT = os.getenv('STUDENT_DEPARTMENT', 'Department')
PROJECT_TEAM = [
    'Student Leadership Team',
    'Faculty Learning Partners',
    'Product and Design Contributors',
]
SKILL_TAGS = [
    'Python', 'Web Development', 'UI/UX', 'Power BI', 'Communication', 'Digital Marketing', 'Data Analytics'
]

# Keep this file easy to edit later when real college/brand content is provided.
