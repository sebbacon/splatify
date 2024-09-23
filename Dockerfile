FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the Python script and requirements file
COPY make_list.py .
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Command to run the script (this won't be used by cron, but can be useful for testing)
CMD ["python", "make_list.py"]