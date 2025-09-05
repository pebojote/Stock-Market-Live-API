# Use an official lightweight Python image
FROM python:3.9-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the Python dependencies
# Using --no-cache-dir makes the image smaller
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port the app runs on (Render provides this as an env var)
EXPOSE 10000

# Command to run the application using Waitress
# This is the "shell form" which correctly substitutes the ${PORT} variable.
CMD waitress-serve --host=0.0.0.0 --port=${PORT} main:app

