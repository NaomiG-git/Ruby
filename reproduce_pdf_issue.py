
import sys
import os

# Add src to path
sys.path.append(os.getcwd())

from src.agent.builtins.pdf import create_pdf_document

# Mimic the data from pdf_debug.txt
# Content (first 100 chars): [{'paragraphs': ['Welcome to Artist Studio Pro Gold. This guide is a complete reference for using yo

fake_content = [
    {
        'paragraphs': [
            "# Artist Studio Pro Gold",
            "Welcome to Artist Studio Pro Gold.",
            "## Getting Started",
            "This is a test paragraph.",
            "**Bold Heading**",
            "Regular text."
        ]
    }
]

print("--- Testing create_pdf_document with wrapped content ---")
result = create_pdf_document(
    filename="C:\\Users\\grind\\Desktop\\DEBUG_PDF_TEST.pdf", 
    title="Debug Title", 
    content=fake_content
)
print("Result:", result)
