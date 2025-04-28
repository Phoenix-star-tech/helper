from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
from flask import flash
import os
import random
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'karthik57'


# Base paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
DATABASE_URL = "postgresql://postgres.beuvyrvloopqgffoscrd:karthik57@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Create the 'users' table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT,
                account_type TEXT,
                phone TEXT,
                business_type TEXT,
                location TEXT,
                bio TEXT,
                profile_pic TEXT,
                price TEXT
            )
        ''')

        # Create the 'services' table (used to store different service types)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id SERIAL PRIMARY KEY,
                service_name TEXT UNIQUE
            )
        ''')

        # Create the 'locations' table (used to store locations)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS locations (
                id SERIAL PRIMARY KEY,
                location_name TEXT UNIQUE
            )
        ''')

        # Create the 'feedback' table
        cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                to_user TEXT NOT NULL,
                from_user TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT NOT NULL,
                reply TEXT
            )
        ''')

        # Create the 'reports' table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                reported_user TEXT NOT NULL,
                reported_by TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        ''')

        # Create the 'orders' table
        cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL,  -- Renamed from 'user' to 'username'
        service_id INT NOT NULL,
        location TEXT NOT NULL,
        order_message TEXT,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
''')


        # Create the 'notifications' table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                to_user TEXT NOT NULL,
                from_user TEXT NOT NULL,
                order_id INTEGER NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )
        ''')

        conn.commit()

# Routes
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'adime' and password == 'adime123':
            session['username'] = username
            return redirect(url_for('admin_dashboard'))

        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
            user = cursor.fetchone()
            if user:
                session['username'] = username
                return redirect(url_for('home'))
            else:
                return "Invalid username or password"
    return render_template('login.html')

@app.route('/home')
def home():
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT DISTINCT business_type FROM users WHERE account_type='business'")
        services_from_db = [row['business_type'] for row in cursor.fetchall()]        
        cursor.execute("SELECT username FROM users WHERE account_type='business'")
        business_usernames = [row['username'] for row in cursor.fetchall()]

    predefined_services = [
        'House Cleaning', 'Kitchen Cleaning', 'Bathroom Cleaning', 'Room Cleaning', 
        'Plumbing', 'Motor Repair', 'Electrician', 'Two wheeler', 'Three wheeler', 
        'Four wheeler', 'Heavy Vehicle'
    ]    
    all_services = list(set(services_from_db + predefined_services))    
    random.shuffle(all_services)    
    random_services = all_services[:6]    
    service_images = {
        'House Cleaning': 'house_cleaning.jpg',
        'Kitchen Cleaning': 'kitchen_cleaning.jpg',
        'Bathroom Cleaning': 'bathroom_cleaning.jpg',
        'Room Cleaning': 'house_cleaning.jpg',
        'Plumbing': 'plumbing.jpg',
        'Motor Repair': 'house_cleaning.png',
        'Electrician': 'electrician.jpg',
        'Two wheeler': 'two_wheeler.jpg',
        'Three wheeler': 'three_wheeler.jpg',
        'Four wheeler': 'four_wheeler.jpg',
        'Heavy Vehicle': 'heavy_vechile.jpg'
    }   
    random_service_images = {service: service_images.get(service, '') for service in random_services}

    return render_template('home.html', services=random_services, service_images=random_service_images, business_usernames=business_usernames)

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('q', '')  # Get the search query from the URL parameters
    services = []
    business_users = []

    if query:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Search for services
            cursor.execute("""
                SELECT * FROM services
                WHERE service_name ILIKE %s
            """, (f'%{query}%',))
            services = cursor.fetchall()

            # Search for businesses based on location and business type
            cursor.execute("""
                SELECT username, business_type, location FROM users
                WHERE (username ILIKE %s OR location ILIKE %s) AND account_type = 'business'
            """, (f'%{query}%', f'%{query}%'))
            business_users = cursor.fetchall()

    return render_template('search.html', 
                       query=query, 
                       service_results=services, 
                       business_results=business_users)

@app.route('/admin')
def admin_dashboard():
    if 'username' not in session or session['username'] != 'adime':
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE username != 'adime'")
        users = cursor.fetchall()

        cursor.execute("SELECT reported_user, COUNT(*) as report_count FROM reports GROUP BY reported_user")
        reported_users = cursor.fetchall()

    return render_template('adime.html', users=users, reported_users=reported_users)

@app.route('/delete_user/<username>', methods=['POST'])
def delete_user(username):
    if 'username' not in session or session['username'] != 'adime':
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username=%s", (username,))
        conn.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/signup')
def signup():
    return render_template('signup.html')

@app.route('/signup/business', methods=['GET', 'POST'])
def signup_business():
    if request.method == 'POST':
        # Ensure username and password are provided
        username = request.form['username']
        password = request.form['password']
        phone = request.form['phone']
        business_type = request.form['business_type']
        location = request.form['location']
        bio = request.form.get('bio', '')  # Default to empty string if not provided
        price = request.form.get('price', '')  # Default to empty string if not provided

        # Handle file upload (profile picture)
        profile_pic_file = request.files.get('profile_pic')
        filename = ''
        if profile_pic_file and allowed_file(profile_pic_file.filename):
            filename = secure_filename(profile_pic_file.filename)
            profile_pic_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Insert user details into 'users' table
                cursor.execute("""
                    INSERT INTO users 
                    (username, password, account_type, phone, business_type, location, bio, price, profile_pic) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (username, password, 'business', phone, business_type, location, bio, price, filename))

                # Insert business type into 'services' table if it's not already there
                cursor.execute("""
                    INSERT INTO services (service_name) 
                    VALUES (%s)
                    ON CONFLICT DO NOTHING
                """, (business_type,))

                # Insert location into 'locations' table if it's not already there
                cursor.execute("""
                    INSERT INTO locations (location_name) 
                    VALUES (%s)
                    ON CONFLICT DO NOTHING
                """, (location,))

                conn.commit()

                # Redirect to login page after successful signup
                return redirect(url_for('login'))

        except Exception as e:
            # Handle any database errors
            print(f"Error: {e}")
            flash('An error occurred during registration. Please try again.', 'danger')

    return render_template('signup_business.html')

@app.route('/signup/user', methods=['GET', 'POST'])
def signup_user():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        phone = request.form['phone']
        profile_pic_file = request.files.get('profile_pic')
        filename = ''
        if profile_pic_file and allowed_file(profile_pic_file.filename):
            filename = secure_filename(profile_pic_file.filename)
            profile_pic_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE username=%s", (username,))
            if cursor.fetchone():
                error = "Username already exists. Please choose a different one."
            else:
                try:
                    cursor.execute("INSERT INTO users (username, password, account_type, phone, profile_pic) VALUES (%s, %s, %s, %s, %s)", 
                                (username, password, 'user', phone, filename))
                    conn.commit()
                    return redirect(url_for('login'))
                except psycopg2.IntegrityError:
                    error = "An error occurred. Please try again."
    return render_template('signup_user.html', error=error)

@app.route('/profile')
@app.route('/profile/<username>')
def profile(username=None):
    if username is None:
        if 'username' not in session:
            return redirect(url_for('login'))
        username = session['username']

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # User details
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()

        # Feedback
        cursor.execute("SELECT * FROM feedback WHERE to_user = %s", (username,))
        feedback = cursor.fetchall()

        # Reports
        cursor.execute("SELECT * FROM reports WHERE reported_user = %s", (username,))
        reports = cursor.fetchall()

        # Past Orders
        cursor.execute("SELECT * FROM orders WHERE provider = %s", (username,))
        past_orders = cursor.fetchall()

        # Notifications
        cursor.execute("SELECT * FROM notifications WHERE to_user = %s ORDER BY id DESC", (username,))
        notifications = cursor.fetchall()

        # Is owner/admin?
        is_owner = session.get('username') == username
        is_admin = session.get('username') == 'adime'

    return render_template('profile.html',
                           user=user,
                           feedback=feedback,
                           reports=reports,
                           past_orders=past_orders,
                           notifications=notifications,
                           is_owner=is_owner,
                           is_admin=is_admin)


@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

    if request.method == 'POST':
        bio = request.form['bio']
        price = request.form['price']
        profile_pic_file = request.files.get('profile_pic')
        filename = user['profile_pic']  # this now works!

        if profile_pic_file and allowed_file(profile_pic_file.filename):
            filename = secure_filename(profile_pic_file.filename)
            profile_pic_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users
                SET bio=%s, price=%s, profile_pic=%s
                WHERE username=%s
            """, (bio, price, filename, username))
            conn.commit()

        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile', username=username))

    return render_template('edit_profile.html', user=user)

@app.route('/order/<service>', methods=['GET', 'POST'])
def order(service):
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']

    # Fetch all registered services and locations
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Fetch all registered services (filtered by status)
        cursor.execute("SELECT service_name FROM services WHERE status = 'registered'")
        services = cursor.fetchall()

        # Fetch all registered locations (filtered by status)
        cursor.execute("SELECT location_name FROM locations WHERE status = 'registered'")
        locations = cursor.fetchall()

    if request.method == 'POST':
        location = request.form['location']
        message = request.form.get('message', '')
        image_file = request.files.get('image')
        image_filename = ''

        if image_file and allowed_file(image_file.filename):
            image_filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orders ("user", service, location, image, message)
                VALUES (%s, %s, %s, %s, %s)
            """, (username, service, location, image_filename, message))
            conn.commit()

        flash('Order placed successfully!', 'success')
        return redirect(url_for('home'))

    # return render_template('order.html', service=service, services=services, locations=locations)
    return render_template('profile.html', service_id=service_id, other_variables=other_values)


@app.route('/order_status/<int:order_id>', methods=['GET', 'POST'])
def order_status(order_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
        order = cursor.fetchone()

        if order['user'] != username:
            flash("You do not have permission to view this order.", "danger")
            return redirect(url_for('home'))

    return render_template('order.html', order=order)

@app.route('/notifications')
def notifications():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT * FROM notifications
            WHERE to_user=%s
        """, (username,))
        notifications = cursor.fetchall()

    return render_template('notifications.html', notifications=notifications)


@app.route('/report/<username>', methods=['GET', 'POST'])
def report(username):
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        reason = request.form['reason']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reports (reported_user, reported_by, reason)
                VALUES (%s, %s, %s)
            """, (username, session['username'], reason))
            conn.commit()

        flash('Report submitted successfully!', 'success')
        return redirect(url_for('profile', username=username))

    return render_template('report.html', username=username)

@app.route('/suggest', methods=['GET'])
def suggest():
    term = request.args.get('term', '')
    suggestions = []

    if term:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get services
        cursor.execute("SELECT service_name FROM services WHERE service_name ILIKE %s LIMIT 5", (f'%{term}%',))
        services = cursor.fetchall()

        # Get business usernames only
        cursor.execute("SELECT username FROM users WHERE account_type = 'business' AND username ILIKE %s LIMIT 5", (f'%{term}%',))
        businesses = cursor.fetchall()

        # Get locations
        cursor.execute("SELECT location_name FROM locations WHERE location_name ILIKE %s LIMIT 5", (f'%{term}%',))
        locations = cursor.fetchall()

        conn.close()

        # Add them to suggestions
        suggestions.extend(service[0] for service in services)
        suggestions.extend(business[0] for business in businesses)
        suggestions.extend(location[0] for location in locations)

    return jsonify(suggestions)

@app.route('/service/<service_name>')
def service(service_name):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT * FROM users 
            WHERE account_type = 'business' AND business_type = %s
        """, (service_name,))
        businesses = cursor.fetchall()
    return render_template('service.html', service_name=service_name, businesses=businesses)

@app.route('/rate_comment/<username>', methods=['POST'])
def rate_comment(username):
    if 'username' not in session:
        flash("You need to log in first!", "warning")
        return redirect(url_for('login'))
    
    # Check if the user is trying to rate their own profile
    if session['username'] == username:
        flash("You cannot rate your own profile!", "danger")
        return redirect(url_for('profile', username=username))
    
    # Retrieve the rating and comment from the form
    rating = request.form['rating']
    comment = request.form['comment']
    
    try:
        # Database connection
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()

        # Check if the user has already rated this profile
        cur.execute("SELECT * FROM feedback WHERE from_user = %s AND to_user = %s", (session['username'], username))
        existing_feedback = cur.fetchone()

        if existing_feedback:
            # If the user has already rated this profile, update the rating and comment
            cur.execute("""
                UPDATE feedback
                SET rating = %s, comment = %s
                WHERE from_user = %s AND to_user = %s
            """, (rating, comment, session['username'], username))
        else:
            # If no existing feedback, insert a new rating and comment
            cur.execute("""
                INSERT INTO feedback (from_user, to_user, rating, comment)
                VALUES (%s, %s, %s, %s)
            """, (session['username'], username, rating, comment))

        conn.commit()
        cur.close()
        conn.close()

        flash("Your rating and comment have been submitted!", "success")
    except Exception as e:
        print(f"Error: {e}")
        flash("Something went wrong. Please try again later.", "danger")

    return redirect(url_for('profile', username=username))

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
