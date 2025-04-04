from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
import MySQLdb.cursors
import re
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)

# Configure secret key for session
app.secret_key = os.urandom(24)

# Configure MySQL connection
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'yourusername' #Change Username according to your sql server
app.config['MYSQL_PASSWORD'] = 'yourpassword' #Change Password according to your sql server
app.config['MYSQL_DB'] = 'voting_system'
app.config['UPLOAD_FOLDER'] = 'static/uploads/'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}

# Initialize MySQL
mysql = MySQL(app)

# Email configuration for OTP sending
EMAIL_ADDRESS = "your_email_address" #add email address to send email with
EMAIL_PASSWORD = "your_email_password" #add Password of that email

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def create_database():
    # Connect to MySQL server (without specifying a database)
    connection = MySQLdb.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD']
    )
    cursor = connection.cursor()

    # Create the voting_system database if it doesn't exist
    cursor.execute("CREATE DATABASE IF NOT EXISTS voting_system")
    connection.commit()
    cursor.close()
    connection.close()

def create_tables():
    cursor = mysql.connection.cursor()

    # Create admins table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            admin_id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL
        )
    ''')

    # Create voters table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS voters (
            voter_id VARCHAR(50) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) NOT NULL UNIQUE,
            phone VARCHAR(15) NOT NULL,
            password VARCHAR(255) NOT NULL,
            has_voted TINYINT(1) NOT NULL DEFAULT 0
        )
    ''')

    # Create parties table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parties (
            party_id INT AUTO_INCREMENT PRIMARY KEY,
            party_name VARCHAR(100) NOT NULL UNIQUE,
            party_symbol VARCHAR(255) NOT NULL,
            votes INT NOT NULL DEFAULT 0
        )
    ''')

    mysql.connection.commit()

    # Insert default admin user if not exists
    cursor.execute("SELECT * FROM admins WHERE username = 'admin'")
    existing_admin = cursor.fetchone()

    if not existing_admin:
        hashed_password = generate_password_hash("admin")  # Hash the default password
        cursor.execute("INSERT INTO admins (username, password) VALUES (%s, %s)", ("admin", hashed_password))
        mysql.connection.commit()
        print("Default admin user created: Username: admin, Password: admin")

    cursor.close()

with app.app_context():
    create_tables()

# Function to send OTP via email
def send_otp(email, otp):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = email
    msg['Subject'] = "Your OTP for Voting System Login"
    
    body = f"Your OTP for login is: {otp}. This OTP is valid for 5 minutes."
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.set_debuglevel(1)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, email, text)
        server.quit()
        return True
    except smtplib.SMTPAuthenticationError:
        print("SMTP Authentication Error: Check your email and password.")
    except smtplib.SMTPConnectError:
        print("SMTP Connection Error: Check your network connection.")
    except Exception as e:
        print(f"Error sending email: {e}")
    return False

# Route for home page
@app.route('/')
def home():
    return render_template('voter/index.html')

# Route for voter registration (admin function)
@app.route('/admin/register_voter', methods=['GET', 'POST'])
def register_voter():
    # Check if admin is logged in
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    msg = ''
    if request.method == 'POST':
        # Get form data
        voter_id = request.form['voter_id']
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        password = generate_password_hash(request.form['password'])
        
        # Check if voter already exists
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM voters WHERE voter_id = %s OR email = %s', (voter_id, email))
        account = cursor.fetchone()
        
        if account:
            msg = 'Voter already exists!'
        elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            msg = 'Invalid email address!'
        elif not re.match(r'[A-Za-z0-9]+', voter_id):
            msg = 'Voter ID must contain only characters and numbers!'
        else:
            # Insert new voter into database
            cursor.execute('INSERT INTO voters VALUES (%s, %s, %s, %s, %s, %s)', 
                         (voter_id, name, email, phone, password, 0))
            mysql.connection.commit()
            msg = 'Voter registered successfully!'
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT voter_id, name, email, phone, has_voted FROM voters')
    voters = cursor.fetchall()
    

    return render_template('admin/register_voter.html', msg=msg)

@app.route('/admin/api/voters', methods=['GET'])
def get_voters():
    if not session.get('admin_logged_in'):
        return {"error": "Unauthorized"}, 403  # Prevent access if not logged in as admin
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT voter_id, name, email, phone, has_voted FROM voters')
    voters = cursor.fetchall()
    
    return {"voters": voters}, 200

# Route for voter login
@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    email = ''
    if request.method == 'POST':
        voter_id = request.form['voter_id']
        password = request.form['password']
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM voters WHERE voter_id = %s', (voter_id,))
        account = cursor.fetchone()
        email = account['email']
        
        if account and check_password_hash(account['password'], password):
            # Generate OTP and save to session
            otp = str(random.randint(100000, 999999))
            session['otp'] = otp
            session['voter_id'] = voter_id
            session['email'] = account['email']
            session['otp_time'] = datetime.now().timestamp()
            
            # Send OTP via email
            if send_otp(account['email'], otp):
                return redirect(url_for('verify_otp'))
            else:
                msg = 'Failed to send OTP. Please try again.'
        else:
            msg = 'Invalid Voter ID or Password!'
    
    return render_template('voter/login.html', msg=msg)

# Route for verify otp
@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    msg = ''
    
    # Check if OTP exists in session, otherwise redirect to login
    if 'otp' not in session:
        return redirect(url_for('login'))
    
    email = session.get('email', '')  # Ensure email is defined
    
    if request.method == 'POST':
        user_otp = request.form['otp']
        stored_otp = session['otp']
        otp_time = session['otp_time']
        
        # Check if OTP is valid (within 5 minutes)
        current_time = datetime.now().timestamp()
        if current_time - otp_time > 300:  # 5 minutes
            msg = 'OTP has expired. Please try again.'
            session.pop('otp', None)
            session.pop('otp_time', None)
            session.pop('email', None)
            return redirect(url_for('login'))
        
        if user_otp == stored_otp:
            session['logged_in'] = True
            session.pop('otp', None)
            session.pop('otp_time', None)
            session.pop('email', None)
            return redirect(url_for('voting_page'))
        else:
            msg = 'Invalid OTP. Please try again.'
    
    return render_template('voter/verify_otp.html', msg=msg, email=email)


# Route for voting page
@app.route('/voting', methods=['GET', 'POST'])
def voting_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    voter_id = session['voter_id']
    
    # Check if the voter has already voted
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT has_voted FROM voters WHERE voter_id = %s', (voter_id,))
    voter = cursor.fetchone()
    
    if voter['has_voted'] == 1:
        return render_template('voter/already_voted.html')
    
    # Get all parties
    cursor.execute('SELECT * FROM parties')
    parties = cursor.fetchall()
    
    if request.method == 'POST':
        party_id = request.form['party']
        
        # Record the vote
        cursor.execute('UPDATE voters SET has_voted = 1 WHERE voter_id = %s', (voter_id,))
        cursor.execute('UPDATE parties SET votes = votes + 1 WHERE party_id = %s', (party_id,))
        mysql.connection.commit()
        
        # Clear session
        session.pop('logged_in', None)
        session.pop('voter_id', None)
        
        return render_template('voter/vote_success.html')
    
    return render_template('voter/voting.html', parties=parties)

# Route for admin login
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    msg = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM admins WHERE username = %s', (username,))
        admin = cursor.fetchone()
        
        if admin and check_password_hash(admin['password'], password):
            session['admin_logged_in'] = True
            session['admin_id'] = admin['admin_id']
            return redirect(url_for('admin_dashboard'))
        else:
            msg = 'Invalid Username or Password!'
    
    return render_template('admin/login.html', msg=msg)

# Route for admin dashboard
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    return render_template('admin/dashboard.html')

@app.route('/admin/api/dashboard-data')
def dashboard_data():
    if not session.get('admin_logged_in'):
        return {"error": "Unauthorized"}, 403

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get total number of voters
    cursor.execute('SELECT COUNT(*) as totalVoters FROM voters')
    total_voters = cursor.fetchone()['totalVoters']

    # Get total votes cast
    cursor.execute('SELECT COUNT(*) as votesCast FROM voters WHERE has_voted = 1')
    votes_cast = cursor.fetchone()['votesCast']

    # Calculate turnout percentage
    turnout_percentage = (votes_cast / total_voters * 100) if total_voters > 0 else 0

    # Get total parties
    cursor.execute('SELECT COUNT(*) as totalParties FROM parties')
    total_parties = cursor.fetchone()['totalParties']

    # Get votes per party
    cursor.execute('SELECT party_name as name, votes FROM parties')
    parties = cursor.fetchall()

    return {
        "totalVoters": total_voters,
        "votesCast": votes_cast,
        "turnoutPercentage": round(turnout_percentage, 2),
        "totalParties": total_parties,
        "parties": parties
    }

# Route for managing parties
@app.route('/admin/manage_parties', methods=['GET', 'POST'])
def manage_parties():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    msg = ''
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Handle adding new party
    if request.method == 'POST' and 'party_name' in request.form:
        party_name = request.form['Party Candidate']
        file = request.files['party_symbol']

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
        
        cursor.execute('INSERT INTO parties (party_name, party_symbol, votes) VALUES (%s, %s, %s)', 
                     (party_name, file_path, 0))
        mysql.connection.commit()
        msg = 'Party added successfully!'
    
    return render_template('admin/manage_parties.html', msg=msg)

@app.route('/admin/api/parties', methods=['GET'])
def get_parties():
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT party_id, party_name, party_symbol, votes FROM parties')
    parties = cursor.fetchall()
    
    return {"parties": parties}, 200

# Route for viewing results
@app.route('/admin/results')
def view_results():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT * FROM parties ORDER BY votes DESC')
    results = cursor.fetchall()
    
    # Get total number of voters and votes cast
    cursor.execute('SELECT COUNT(*) as total FROM voters')
    total_voters = cursor.fetchone()['total']
    
    cursor.execute('SELECT COUNT(*) as voted FROM voters WHERE has_voted = 1')
    votes_cast = cursor.fetchone()['voted']
    
    return render_template('admin/results.html', results=results, total_voters=total_voters, votes_cast=votes_cast)

@app.route('/admin/api/results')
def api_results():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Fetch election results ordered by votes (descending)
    cursor.execute('SELECT party_id, party_name, party_symbol, votes FROM parties ORDER BY votes DESC')
    results = cursor.fetchall()

        # Get total voters
    cursor.execute('SELECT COUNT(*) as total FROM voters')
    total_voters = cursor.fetchone()['total']

        # Get number of votes cast
    cursor.execute('SELECT COUNT(*) as voted FROM voters WHERE has_voted = 1')
    votes_cast = cursor.fetchone()['voted']

    return {
        "results": results,
        "total_voters": total_voters,
        "votes_cast": votes_cast
    }

# Route for admin logout
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_id', None)
    return redirect(url_for('admin_login'))

# Route for voter logout
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('voter_id', None)
    return redirect(url_for('home'))

# Main driver
if __name__ == '__main__':
    app.run(debug=True)