"""PDF export tool for the Langchain agent."""

from datetime import datetime
from pathlib import Path
from langchain_core.tools import tool
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch


@tool
def export_to_pdf(content: str, title: str = "Document", filename: str = "output.pdf") -> str:
    """Export text content to a PDF file.
    
    Args:
        content: The text content to export
        title: Title of the PDF document
        filename: Name of the PDF file to create
        
    Returns:
        Success message with file path
    """
    try:
        output_dir = Path("./outputs")
        output_dir.mkdir(exist_ok=True)
        
        filepath = output_dir / filename
        
        # Create PDF
        doc = SimpleDocTemplate(str(filepath), pagesize=letter)
        story = []
        
        # Define styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor='#1f4788',
            spaceAfter=30,
            alignment=1  # Center alignment
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['BodyText'],
            fontSize=11,
            spaceAfter=12,
            alignment=4  # Justify alignment
        )
        
        # Add title
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 0.3 * inch))
        
        # Add metadata
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        story.append(Paragraph(f"<i>Generated on: {timestamp}</i>", styles['Normal']))
        story.append(Spacer(1, 0.3 * inch))
        
        # Add content
        for paragraph in content.split('\n'):
            if paragraph.strip():
                story.append(Paragraph(paragraph, body_style))
                story.append(Spacer(1, 0.1 * inch))
        
        # Build PDF
        doc.build(story)
        
        return f"PDF successfully exported to {filepath}"
    except Exception as e:
        return f"Error exporting to PDF: {str(e)}"
