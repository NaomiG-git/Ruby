"""PDF tools for Ruby Agent."""

import logging
import os
from typing import List

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from src.agent.tools import FunctionTool


logger = logging.getLogger(__name__)


def create_pdf_document(filename: str, title: str, content: List[dict] = None, **kwargs) -> str:
    """Create a PDF document with structured content.
    
    Args:
        filename: Name of the PDF file to create.
        title: Title of the document.
        content: List of content items dicts.
        **kwargs: Catch-all for legacy arguments (e.g. 'paragraphs').
    """
    # DEBUG: Log inputs to help diagnose missing content
    with open(r"C:\Users\grind\Desktop\pdf_debug.txt", "a") as f:
        f.write(f"\n--- PDF Creation Call ---\n")
        f.write(f"Title: {title}\n")
        f.write(f"Filename: {filename}\n")
        f.write(f"Content Type: {type(content)}\n")
        f.write(f"Kwargs keys: {list(kwargs.keys())}\n")
        if content:
             f.write(f"Content (first 100 chars): {str(content)[:100]}\n")
        else:
             f.write("Content is Empty/None\n")

    # Handle legacy 'paragraphs' argument from older tool definition
    if content is None:
        content = kwargs.get('paragraphs', [])

    # AGGRESSIVE FALLBACK: If content is still empty, look for ANY list or long string in kwargs
    if not content:
        for key, val in kwargs.items():
            if isinstance(val, list) and val:
                content = val
                with open(r"C:\Users\grind\Desktop\pdf_debug.txt", "a") as f: f.write(f"Fallback: Found content in '{key}'\n")
                break
            elif isinstance(val, str) and len(val) > 20:
                content = [val] # Wrap string in list
                with open(r"C:\Users\grind\Desktop\pdf_debug.txt", "a") as f: f.write(f"Fallback: Found text in '{key}'\n")
                break

    # SPECIAL HANDLING: Gemini sometimes wraps content in [{paragraphs: [...]}, {paragraphs: [...]}]
    # We need to flatten this into a single list of content items.
    flat_content = []
    
    # Check if we have the specific nested structure (list of dicts with 'paragraphs')
    # Or just a regular list that needs flattening/unwrapping
    if isinstance(content, list):
         for item in content:
             if isinstance(item, dict) and 'paragraphs' in item:
                 # Found a wrapper block, extend our flat list with its inner content
                 flat_content.extend(item['paragraphs'])
             else:
                 # Regular item (string or legit dict), just add it
                 flat_content.append(item)
         
         if len(flat_content) > len(content) or (len(content) > 0 and isinstance(content[0], dict) and 'paragraphs' in content[0]):
              with open(r"C:\Users\grind\Desktop\pdf_debug.txt", "a") as f: 
                 f.write(f"Unwrapped {len(content)} input blocks into {len(flat_content)} content items.\n")
              content = flat_content

    # Normalize content: If we received a list of strings (legacy), convert to dicts
    normalized_content = []
    for item in content:
        if isinstance(item, str):
            # Legacy string mode: fail gracefully by checking for common formatting
            style = 'Normal'
            text = item
            stripped = item.strip()
            
            # Markdown header detection (tolerant of missing space)
            if stripped.startswith('#'):
                if stripped.startswith('###'):
                    style = 'Heading3'
                    text = stripped.lstrip('#').strip()
                elif stripped.startswith('##'):
                    style = 'Heading2'
                    text = stripped.lstrip('#').strip()
                elif stripped.startswith('#'):
                    style = 'Heading1'
                    text = stripped.lstrip('#').strip()
            elif stripped.startswith('* ') or stripped.startswith('- '):
                style = 'Bullet'
                text = stripped[2:].strip()
            # Detect arbitrary bold text lines as subheadings
            elif stripped.startswith('**') and stripped.endswith('**') and len(stripped) < 100:
                style = 'Heading2' 
                text = stripped[2:-2].strip()
                
            normalized_content.append({'text': text, 'style': style})
        elif isinstance(item, dict):
            normalized_content.append(item)
        else:
            # Fallback for unknown types
            normalized_content.append({'text': str(item), 'style': 'Normal'})
            
    content = normalized_content
    try:
        # Resolve path similar to filesystem tools (simplified for now)
        save_path = os.path.abspath(filename)
        if not save_path.endswith('.pdf'):
            save_path += '.pdf'
            
        doc = SimpleDocTemplate(save_path, pagesize=letter)
        styles = getSampleStyleSheet()
        
        # Define Custom Bold Styles
        styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=styles['Title'],
            fontName='Helvetica-Bold',
            fontSize=24,
            spaceAfter=20,
            textColor=colors.darkblue
        ))
        styles.add(ParagraphStyle(
            name='CustomHeading1',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18,
            spaceAfter=12,
            spaceBefore=12,
            textColor=colors.black
        ))
        styles.add(ParagraphStyle(
            name='CustomHeading2',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=14,
            spaceAfter=10,
            spaceBefore=10,
            textColor=colors.black
        ))
        styles.add(ParagraphStyle(
            name='CustomHeading3',
            parent=styles['Heading3'],
            fontName='Helvetica-BoldOblique',
            fontSize=12,
            spaceAfter=8,
            spaceBefore=8,
            textColor=colors.black
        ))
        
        story = []

        # Add Title
        story.append(Paragraph(title, styles['CustomTitle']))
        story.append(Spacer(1, 12))

        # Add Content
        for item in content:
            text = item.get('text', '')
            style_name = item.get('style', 'Normal')
            
            # Map style names to our custom styles
            if style_name == 'Title':
                style = styles['CustomTitle']
            elif style_name == 'Heading1':
                style = styles['CustomHeading1']
            elif style_name == 'Heading2':
                style = styles['CustomHeading2']
            elif style_name == 'Heading3':
                style = styles['CustomHeading3']
            elif style_name == 'Bullet':
                style = styles.get('Bullet', styles.get('ListBullet', styles['Normal']))
            else:
                style = styles.get(style_name, styles['Normal'])
            
            story.append(Paragraph(text, style))
            story.append(Spacer(1, 12))

        doc.build(story)
        return f"Successfully created PDF: {save_path}"
    except Exception as e:
        logger.error(f"Failed to create PDF: {e}")
        return f"Error creating PDF: {str(e)}"

# Export tools
PDF_TOOLS = [
    FunctionTool(create_pdf_document),
]
