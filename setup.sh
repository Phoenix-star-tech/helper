#!/bin/bash

# Set project directory
PROJECT_DIR="mr_helper"

# Create main project folder
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR

# Create necessary directories
mkdir -p static templates

# Create files
touch app.py static/styles.css
touch templates/{base.html,login.html,signup.html,signup_business.html,signup_user.html,profile.html,home.html}

# Write content to app.py
cat > app.py <<EOF
from flask import Flask, render_template, request, redirect, session, url_for

app = Flask(__name__)
app.secret_key = 'secretkey'

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # Dummy authentication (Replace with database logic)
        if username == "adime" and password == "adime123":
            session['user'] = username
            return redirect(url_for('profile'))
        else:
            return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')

@app.route('/signup')
def signup():
    return render_template('signup.html')

@app.route('/profile')
def profile():
    if 'user' in session:
        return render_template('profile.html', user={'username': session['user'], 'account_type': 'user', 'phone': '1234567890'})
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
EOF

# Write content to base.html
cat > templates/base.html <<EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Mr. Helper{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
</head>
<body>
    <nav>
        <a href="{{ url_for('home') }}">Home</a>
        {% if 'user' in session %}
            <a href="{{ url_for('profile') }}">Profile</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        {% else %}
            <a href="{{ url_for('login') }}">Login</a>
        {% endif %}
    </nav>
    <div class="container">
        {% block content %}{% endblock %}
    </div>
</body>
</html>
EOF

# Write content to login.html
cat > templates/login.html <<EOF
{% extends 'base.html' %}
{% block title %}Login - Mr. Helper{% endblock %}
{% block content %}
<h2>Login</h2>
<form method="POST">
    <label>Username:</label>
    <input type="text" name="username" required>
    <label>Password:</label>
    <input type="password" name="password" required>
    <button type="submit">Login</button>
</form>
<p>Don't have an account? <a href="{{ url_for('signup') }}">Create Account</a></p>
{% if error %}
<p class="error">{{ error }}</p>
{% endif %}
{% endblock %}
EOF

# Write content to signup.html
cat > templates/signup.html <<EOF
{% extends 'base.html' %}
{% block title %}Signup - Mr. Helper{% endblock %}
{% block content %}
<h2>Signup</h2>
<p>Select account type:</p>
<a href="{{ url_for('signup') }}"><button>For Business</button></a>
<a href="{{ url_for('signup') }}"><button>For User</button></a>
{% endblock %}
EOF

# Write content to profile.html
cat > templates/profile.html <<EOF
{% extends 'base.html' %}
{% block title %}Profile - Mr. Helper{% endblock %}
{% block content %}
<h2>Profile</h2>
<p>Username: {{ user.username }}</p>
<p>Phone: {{ user.phone }}</p>
{% if user.account_type == 'business' %}
    <p>Business Details Coming Soon...</p>
{% else %}
    <p>Past Orders Coming Soon...</p>
{% endif %}
{% endblock %}
EOF

# Write content to home.html
cat > templates/home.html <<EOF
{% extends 'base.html' %}
{% block title %}Home - Mr. Helper{% endblock %}
{% block content %}
<h2>Welcome to Mr. Helper</h2>
<form method="GET">
    <input type="text" name="search" placeholder="Search services...">
    <button type="submit">Search</button>
</form>
{% endblock %}
EOF

# Write content to CSS file
cat > static/styles.css <<EOF
body {
    font-family: Arial, sans-serif;
    margin: 0;
    padding: 0;
    background-color: #f8f9fa;
    color: #333;
}
nav {
    background-color: #ff6600;
    padding: 10px;
    text-align: center;
}
nav a {
    color: white;
    text-decoration: none;
    margin: 0 15px;
    font-size: 18px;
}
.container {
    max-width: 600px;
    margin: 30px auto;
    padding: 20px;
    background-color: white;
    box-shadow: 0px 0px 10px rgba(0, 0, 0, 0.1);
    border-radius: 10px;
}
h2 {
    text-align: center;
    color: #ff6600;
}
form {
    display: flex;
    flex-direction: column;
    gap: 10px;
}
input, select, textarea {
    padding: 8px;
    border: 1px solid #ccc;
    border-radius: 5px;
    font-size: 16px;
}
button {
    background-color: #ff6600;
    color: white;
    padding: 10px;
    border: none;
    border-radius: 5px;
    cursor: pointer;
    font-size: 18px;
}
EOF

# Display success message
echo "Project setup complete! Run 'cd mr_helper' and then 'python app.py' to start the app."
