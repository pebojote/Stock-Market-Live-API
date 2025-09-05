# Use an official lightweight Python image
FROM python:3.9-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port the app runs on
# Gunicorn will bind to the PORT environment variable provided by Render
EXPOSE 10000

# Command to run the application using Gunicorn
# This shell form allows the ${PORT} variable to be expanded correctly.
CMD gunicorn --workers 4 --bind 0.0.0.0:${PORT} main:app
