Prerequisites:
--------------------

1.  Python:
    * Version: 3.11.9 is strongly recommended. (Download from: https://www.python.org/downloads/release/python-3119/)
    * Ensure Python is added to your system's PATH during installation.

2.  Build Tools for Visual Studio 2022:
    * Required for compiling some Python package dependencies.
    * Download from: https://visualstudio.microsoft.com/downloads/ (Scroll to "Tools for Visual Studio" -> "Build Tools for Visual Studio 2022").
    * IMPORTANT: During installation, select the "Desktop development with C++" workload.

3.  Rust Compiler:
    * Required for compiling other Python package dependencies.
    * Install via rustup: https://rustup.rs/

--------------------
Setup and Running Instructions:
--------------------

FIRST CONFIGURE YOUR .env FILE!!!


(Run these commands line by line in your project's root directory using a terminal like PowerShell in VS Code)

1.  Create a Python virtual environment:
    python -m venv venv

2.  Set PowerShell Execution Policy (if script execution is disabled):
    (This allows the activation script to run in the current session only)
    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

3.  Activate the virtual environment:
    * For PowerShell:
        .\venv\Scripts\Activate.ps1
    * For Command Prompt (cmd.exe):
        .\venv\Scripts\activate.bat
    * For Git Bash / Linux / macOS:
        source venv/bin/activate

    (Your terminal prompt should now start with "(venv)")

4.  Install Python dependencies:
    (This may take several minutes)
    pip install -r requirements.txt

5.  Initial Server Run (for spaCy model download):
    (The first time you run this, it will download the spaCy model 'en_core_web_trf'. Please be patient as this is a large file.)
    uvicorn app.main:app

    Wait for the message "Application startup complete." then stop the server with CTRL+C.

6.  Run the Development Server:
    uvicorn app.main:app --reload

--------------------
Testing the API:
--------------------

1.  Once the server is running (Step 6 above), open your web browser.
2.  Navigate to: http://127.0.0.1:8000/docs
3.  This will show the FastAPI interactive API documentation.
4.  You can test the endpoints:
    * Use the POST /documents/mask endpoint to upload a sample PDF (e.g., `sample.pdf` from the project) and get a `file_id`.
    * Use the GET /documents/unmask/{file_id} endpoint with the `file_id` to retrieve the unmasked PDF.

Test the API!!! Enjoy!





this worked, thanks. I noticed that for some entries that span over one line ( eg Lim Hee Bingm where Lim is on the line before and Hee Bing is on the next line, it correctly identifies it as one person, but it labels person1 twice here, one on the line before one on the line after.) this is an issue as the reversible masking algo will replace it with two instances of person 1?
