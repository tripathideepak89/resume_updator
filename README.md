# Resume Updater & Cover Letter Generator

A CLI utility that takes a **Job Description** (`.txt`) as input, tailors your resume and generates a cover letter as **compressed PDFs**.

Uses **Hugging Face Inference API** (free tier, Qwen2.5-72B) for AI-powered tailoring, with an automatic keyword-matching fallback when no API is available.

## Architecture

```mermaid
graph TB
    subgraph Input
        JD["📄 Job Description<br/>(*.txt)"]
        RD["📋 Resume Data<br/>(resume_data.json)"]
    end

    subgraph "Core Engine (main.py)"
        PARSE["JD Parser<br/>Company Name Extraction<br/>Keyword Extraction"]
        
        subgraph "AI Layer"
            HF["Hugging Face API<br/>Qwen2.5-72B-Instruct"]
            KW["Keyword-Match<br/>Fallback Engine"]
        end

        TAILOR["Resume Tailor<br/>• Rewrite Summary<br/>• Reorder Skills<br/>• Reframe Bullets"]
        
        COVER["Cover Letter Generator<br/>• Template Fallback<br/>• AI-Powered Writing"]
    end

    subgraph "PDF Renderer (ReportLab)"
        RPDF["Resume PDF Builder<br/>• Header & Contact<br/>• Skills Matrix<br/>• Experience<br/>• Education"]
        CPDF["Cover Letter PDF Builder<br/>• Letterhead<br/>• Body Paragraphs<br/>• Sign-off"]
    end

    subgraph Output
        ROUT["📄 Resume_Company_timestamp.pdf"]
        COUT["📄 CoverLetter_Company_timestamp.pdf"]
    end

    JD --> PARSE
    RD --> TAILOR
    RD --> COVER
    PARSE --> HF
    PARSE --> KW
    HF -->|AI response| TAILOR
    HF -->|AI response| COVER
    KW -->|Fallback| TAILOR
    KW -->|Fallback| COVER
    TAILOR --> RPDF
    COVER --> CPDF
    RPDF -->|Compressed PDF| ROUT
    CPDF -->|Compressed PDF| COUT

    style JD fill:#E3F2FD,stroke:#1565C0,color:#000
    style RD fill:#E3F2FD,stroke:#1565C0,color:#000
    style HF fill:#FFF3E0,stroke:#E65100,color:#000
    style KW fill:#FFF3E0,stroke:#E65100,color:#000
    style ROUT fill:#E8F5E9,stroke:#2E7D32,color:#000
    style COUT fill:#E8F5E9,stroke:#2E7D32,color:#000
```

## Execution Flow

```mermaid
flowchart TD
    START(["▶ python main.py jd_file.txt"]) --> READ_JD["Read Job Description<br/>from .txt file"]
    READ_JD --> READ_RESUME["Load resume_data.json"]
    READ_RESUME --> DETECT["Detect Company Name<br/>from JD text"]
    DETECT --> CHECK_TOKEN{"HF_TOKEN<br/>set?"}

    CHECK_TOKEN -->|Yes| CHECK_LIB{"huggingface_hub<br/>installed?"}
    CHECK_TOKEN -->|No| KEYWORD_MODE["Keyword-Match Mode"]
    CHECK_LIB -->|Yes| AI_MODE["AI Mode<br/>Hugging Face API"]
    CHECK_LIB -->|No| KEYWORD_MODE

    AI_MODE --> CALL_TAILOR["Call LLM: Tailor Resume<br/>• Rewrite summary<br/>• Reorder skills<br/>• Reframe experience"]
    AI_MODE --> CALL_COVER["Call LLM: Generate<br/>Cover Letter"]

    CALL_TAILOR --> LLM_OK1{"Valid JSON<br/>response?"}
    LLM_OK1 -->|Yes| TAILORED["Tailored Resume Data"]
    LLM_OK1 -->|No| KW_RESUME

    CALL_COVER --> LLM_OK2{"Response<br/>length > 50?"}
    LLM_OK2 -->|Yes| COVER_TEXT["Cover Letter Text"]
    LLM_OK2 -->|No| KW_COVER

    KEYWORD_MODE --> KW_RESUME["Keyword Fallback:<br/>• Extract JD keywords<br/>• Reorder skills by match<br/>• Sort bullets by relevance"]
    KEYWORD_MODE --> KW_COVER["Template Fallback:<br/>• Find best matching role<br/>• Map skills to JD<br/>• Generate from template"]

    KW_RESUME --> TAILORED
    KW_COVER --> COVER_TEXT

    TAILORED --> BUILD_RESUME["Build Resume PDF<br/>ReportLab / A4 / Compressed"]
    COVER_TEXT --> BUILD_COVER["Build Cover Letter PDF<br/>ReportLab / A4 / Compressed"]

    BUILD_RESUME --> OUT_R["📄 output/Resume_Company_ts.pdf"]
    BUILD_COVER --> OUT_C["📄 output/CoverLetter_Company_ts.pdf"]

    OUT_R --> DONE(["✅ Done!"])
    OUT_C --> DONE

    style START fill:#1565C0,stroke:#0D47A1,color:#fff
    style DONE fill:#2E7D32,stroke:#1B5E20,color:#fff
    style AI_MODE fill:#FFF3E0,stroke:#E65100,color:#000
    style KEYWORD_MODE fill:#F3E5F5,stroke:#6A1B9A,color:#000
    style OUT_R fill:#E8F5E9,stroke:#2E7D32,color:#000
    style OUT_C fill:#E8F5E9,stroke:#2E7D32,color:#000
```

## Setup

```bash
pip install -r requirements.txt
```

### AI Mode (recommended)

Get a free token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) with **Inference Providers** permission enabled.

```bash
export HF_TOKEN="hf_your_token_here"
```

### Keyword-Match Mode (no token needed)

Works out of the box — parses JD for keywords, reorders skills/bullets, and generates a template-based cover letter.

## Usage

```bash
python main.py <jd_file.txt> [--output output_dir]
```

### Examples

```bash
# Basic usage
python main.py job_posting.txt

# Custom output directory
python main.py job_posting.txt --output ./pdfs
```

## Output

Two compressed PDF files named after the detected company:

```
output/Resume_FDJ_UNITED_20260420_103807.pdf
output/CoverLetter_FDJ_UNITED_20260420_103807.pdf
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | Main utility script |
| `resume_data.json` | Your structured resume data (edit with your details) |
| `requirements.txt` | Python dependencies |
| `sample_jd.txt` | Example job description for testing |
| `.env.example` | Template for environment variables |

## How It Works

1. Reads your base resume from `resume_data.json`
2. Reads the job description from the input `.txt` file
3. Detects the company name from the JD for output file naming
4. Uses Hugging Face LLM (or keyword matching) to tailor summary, skills, and experience bullets
5. Generates a matching cover letter
6. Renders both as professionally formatted, compressed PDFs
