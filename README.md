# Plato - Course Outline to Calendar Converter

A web application that automatically extracts course information from Western University course outline PDFs and generates iCalendar (`.ics`) files compatible with Google Calendar, Apple Calendar, and Outlook.

## Overview

Plato processes course outline PDFs to extract:

* Course information (code, name, term)
* Lecture and lab schedules (days, times, locations)
* Assessments (assignments, quizzes, exams with due dates and weights)
* Relative date rules (for example, “24 hours after lab”)

The extracted data is then converted into a calendar file with:

* Recurring lecture and lab events
* Assessment due dates
* Study plan events with configurable lead times based on assessment weights

## Features

* Automatic PDF extraction using a multi-layered approach
* Document structure analysis with layout-aware extraction
* Section segmentation for more accurate field extraction
* Policy text filtering to reduce false positives
* Constrained selection to ensure assessment weights total approximately 100%
* Interactive review interface with inline editing
* Manual section and assessment addition
* Configurable study plan lead times
* Session-based caching for performance
* Force refresh option to re-extract cached PDFs
* Dark mode and responsive design
* Clean, minimalist UI

## Installation

### Prerequisites

* Python 3.8 or higher
* `pip` (Python package manager)

### Local Setup

Clone the repository:

```bash
git clone https://github.com/KalpKan/Plato.git
cd Plato
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the development server:

```bash
python3 src/app.py
```

Open your browser and navigate to:

```bash
http://localhost:5000
```

## Usage

### Basic Workflow

1. **Upload PDF**
   Click **Choose File** and select your course outline PDF.

2. **Review Extraction**
   The system extracts course information and displays it for review.

3. **Edit Fields**
   Click any field to edit inline, including dates, weights, and titles.

4. **Add Missing Data**
   Use **Add Section** or **Add Assessment** if anything is missing.

5. **Select Sections**
   If multiple lecture or lab sections exist, select yours from the dropdowns.

6. **Review Assessments**
   Check and edit ambiguous assessments if needed.

7. **Configure Lead Times**
   Adjust study plan lead times based on your preferences.

8. **Generate Calendar**
   Click **Generate Calendar** to download the `.ics` file.

### Manual Mode

If PDF extraction fails or you prefer to enter data manually:

1. Click **Manual Mode** on the upload page
2. Enter term dates, section schedules, and assessments
3. Generate the `.ics` file from manual inputs

## Importing to Calendar

### Google Calendar

1. Open Google Calendar
2. Click the **+** button, then **Import**
3. Select the generated `.ics` file
4. Choose your calendar and click **Import**

### Apple Calendar

1. Open the Calendar app
2. Click **File → Import**
3. Select the generated `.ics` file
4. Choose your calendar and click **Import**

### Outlook

1. Open Outlook
2. Go to **File → Open & Export → Import/Export**
3. Select **Import an iCalendar (.ics) or vCalendar file**
4. Choose the generated `.ics` file

## Project Structure

```text
Plato/
├── src/
│   ├── app.py                  # Flask web application
│   ├── models.py               # Data models (dataclasses)
│   ├── pdf_extractor.py        # PDF extraction engine
│   ├── document_structure.py   # Document structure analysis
│   ├── assessment_extractor.py # Assessment extraction pipeline
│   ├── course_extractor.py     # Course info extraction
│   ├── rule_resolver.py        # Relative date rule resolution
│   ├── study_plan.py           # Study plan generation
│   ├── icalendar_gen.py        # iCalendar file generation
│   ├── cache.py                # Caching system
│   └── main.py                 # CLI entry point
├── templates/
│   ├── base.html               # Base template
│   ├── index.html              # Landing page
│   ├── review.html             # Review/edit page
│   ├── manual.html             # Manual entry page
│   └── error.html              # Error page
├── static/
│   ├── style.css               # Stylesheet
│   └── app.js                  # Client-side JavaScript
├── course_outlines/            # Test PDFs (not in git)
├── test_course_outlines/       # Additional test PDFs
├── requirements.txt            # Python dependencies
├── Procfile                    # Railway deployment config
├── Dockerfile                  # Docker configuration
└── README.md                   # Project documentation
```

## How It Works

### 1. Document Structure Analysis

* Extracts text blocks with layout metadata such as font sizes and positions
* Reconstructs lines from blocks using y-coordinate clustering
* Detects tables using `pdfplumber` and reconstructed aligned lines
* Identifies major sections such as Evaluation and Course Information

### 2. Section Segmentation

* Detects headings using font size, bold styling, and keywords
* Creates section ranges with start and end pages and positions
* Restricts extraction to relevant sections, such as pulling assessments only from the Evaluation section

### 3. Assessment Extraction

* Generates candidates from tables, reconstructed tables, and inline patterns
* Scores candidates based on weight validity, assessment-related language, and section context
* Filters policy-style text to reduce false positives
* Selects the most plausible assessment set while keeping total weights near 100%

### 4. Course Information Extraction

* Uses layout-based ranking with font size, position, and proximity to the course code
* Filters out generic labels like Department and Faculty
* Falls back to PDF metadata when needed

### 5. Rule Resolution

* Parses relative deadline rules such as “24 hours after lab”
* Matches rules to existing assessments where possible
* Generates per-occurrence assessments when necessary
* Resolves all rules into absolute datetimes using recurring schedules

### 6. Study Plan Generation

Default lead times based on assessment weight:

* 0–10%: 3 days
* 10–20%: 5 days
* 20–30%: 7 days
* 30–40%: 10 days
* 40–50%: 14 days
* 50%+: 21 days
* Finals: always 21 days

Lead times are user-configurable for each weight range.

### 7. Calendar Generation

* Creates recurring lecture and lab events using RRULE
* Creates assessment due-date events
* Creates study plan start events
* Uses timezone-aware datetimes for `America/Toronto`
* Includes `VTIMEZONE` for better compatibility across calendar apps

## Caching

* **Extraction Cache:** stores extracted data keyed by PDF hash (`SHA-256`)
* **User Choices Cache:** stores section selections and lead-time overrides keyed by session
* **Force Refresh:** bypasses cache and re-extracts the PDF when needed

## Performance

Tested on 39 course outline PDFs:

* **Extraction Success:** 100% (39/39)
* **Perfect Weight Accuracy (90–110%):** 87% (34/39)
* **Good Weight Accuracy (80–120%):** 92% (36/39)
* **Assessment Extraction:** 97% (38/39 have 2+ assessments)
* **Course Name Extraction:** 100% (39/39)

## Limitations

* PDF format only, no DOCX support
* Maximum file size: 5MB
* Works best with structured course outlines and clear assessment tables
* Some ambiguous data may still require manual review
* Lecture and lab schedules are not always included in PDFs, so manual entry may still be needed

## Development

### Running Tests

```bash
# Comprehensive extraction test
python3 test_comprehensive.py

# New extraction pipeline test
python3 test_new_extraction.py
```

### Code Structure

The codebase is organized into focused modules:

* `models.py` — data structures
* `pdf_extractor.py` — main extraction orchestrator
* `document_structure.py` — layout analysis and section segmentation
* `assessment_extractor.py` — candidate generation, scoring, and selection
* `course_extractor.py` — course information extraction
* `rule_resolver.py` — relative date rule resolution
* `study_plan.py` — study plan generation
* `icalendar_gen.py` — calendar file generation
* `cache.py` — caching system

## Deployment

See `DEPLOYMENT.md` for detailed deployment instructions for Railway with Supabase.

## Documentation

* `PROJECT_OVERVIEW.md` — comprehensive project documentation
* `ARCHITECTURE.md` — system architecture and component responsibilities
* `EXTRACTION_PLAN.md` — detailed extraction algorithm documentation
* `DEPLOYMENT.md` — deployment guide

## License

This project is provided as-is for educational purposes.

## Support

For issues or questions, refer to the documentation files or open an issue on GitHub.

## Credits

**Co-Developed by Zeeshan Chaudhry and Kalp Kansara**

## Disclaimer

This tool is not affiliated with Western University. It is an independent project designed to help students manage their course schedules.
