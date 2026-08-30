import html
import re

class ArticleFormatter:
    """Formatter to convert AI Structured Output into clean, highly professional HTML for Blogger following TahtElDoo style."""

    FONT_FAMILY = "'Lato', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
    STRONG_STYLE = f"font-family: {FONT_FAMILY} !important; font-weight: bold; color: #000000;"
    STRONG_OPEN = f'<strong style="{STRONG_STYLE}">'

    @classmethod
    def _bold_phrase_safely(cls, text: str, phrase: str) -> str:
        """
        Safely bolds a target phrase in HTML text only when it is not already inside a bold/strong tag.
        Enforces exact font-family matching to prevent theme font overrides.
        """
        if not text or not phrase:
            return text

        phrase_clean = phrase.strip()
        phrase_escaped = html.escape(phrase_clean)
        if not phrase_escaped or phrase_escaped not in text:
            return text

        parts = re.split(r"(<[^>]+>)", text)
        inside_bold = False
        formatted_parts = []

        for part in parts:
            if not part:
                continue

            if part.startswith("<") and part.endswith(">"):
                tag_lower = part.lower().strip()
                if re.search(r"<(strong|b)\b", tag_lower):
                    inside_bold = True
                elif re.search(r"</(strong|b)\s*>", tag_lower):
                    inside_bold = False
                formatted_parts.append(part)
            else:
                if not inside_bold:
                    part = part.replace(phrase_escaped, f"{cls.STRONG_OPEN}{phrase_escaped}</strong>")
                formatted_parts.append(part)

        return "".join(formatted_parts)

    @classmethod
    def _format_text_content(cls, text: str, name: str = None) -> str:
        """
        Escapes HTML characters safely while converting markdown **text** or <strong>text</strong> into proper <strong> HTML tags.
        Enforces exact inline font-family matching so bold text matches the surrounding font 100%.
        """
        if not text:
            return ""

        text = str(text).strip()

        # 1. Protect existing <strong> and <b> tags from being escaped
        text = re.sub(r'<\s*strong\b[^>]*>', '___STRONG_OPEN___', text, flags=re.IGNORECASE)
        text = re.sub(r'<\s*/\s*strong\s*>', '___STRONG_CLOSE___', text, flags=re.IGNORECASE)
        text = re.sub(r'<\s*b\b[^>]*>', '___STRONG_OPEN___', text, flags=re.IGNORECASE)
        text = re.sub(r'<\s*/\s*b\s*>', '___STRONG_CLOSE___', text, flags=re.IGNORECASE)

        # 2. Convert markdown ***text*** and **text** into placeholders
        text = re.sub(r'\*\*\*(.*?)\*\*\*', r'___STRONG_OPEN___\1___STRONG_CLOSE___', text, flags=re.DOTALL)
        text = re.sub(r'\*\*(.*?)\*\*', r'___STRONG_OPEN___\1___STRONG_CLOSE___', text, flags=re.DOTALL)

        # 3. Escape raw HTML characters safely
        escaped = html.escape(text)

        # 4. Restore standard <strong> HTML tags with explicit font-family matching
        formatted = escaped.replace('___STRONG_OPEN___', cls.STRONG_OPEN).replace('___STRONG_CLOSE___', '</strong>')

        # 5. Always bold "جريدة تحت الضوء الإخبارية" safely if not already bolded
        formatted = cls._bold_phrase_safely(formatted, "جريدة تحت الضوء الإخبارية")

        # 6. Always bold entity name safely if provided and not already bolded
        if name:
            name_clean = name.strip()
            if name_clean and len(name_clean) > 2:
                formatted = cls._bold_phrase_safely(formatted, name_clean)

        # 7. Flatten any accidental nested bold tags
        prev = None
        while prev != formatted:
            prev = formatted
            formatted = re.sub(r'<strong\b[^>]*>\s*<strong\b[^>]*>(.*?)</strong>\s*<\/strong>', f'{cls.STRONG_OPEN}\\1</strong>', formatted, flags=re.DOTALL | re.IGNORECASE)

        return formatted

    @classmethod
    def json_to_html(cls, ai_data: dict, image_url: str = None) -> str:
        """
        Converts structured JSON from AI into elegant, formal journalistic HTML:
        - font-family: 'Lato', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
        - font-size: 14px;
        - font-weight: 400;
        - line-height: 1.7;
        - color: #000000;
        - Bold headings (#000000, font-weight: bold, font-size: 18px)
        - Highlighted important terms wrapped in clean <strong>...</strong> matching font family
        - Compact centered image (max-width: 330px)
        """
        raw_lead = ai_data.get("lead_paragraph", "")
        sections = ai_data.get("sections", [])
        client_name = ai_data.get("client_name", "")

        # Format lead paragraph with bolding support
        lead_paragraph = cls._format_text_content(raw_lead, name=client_name)

        # Image HTML block (Compact 180px thumbnail display)
        if image_url:
            image_html = f"""
<div style="text-align: center; margin: 12px 0;">
    <img src="{image_url}" alt="صورة الخبر" style="max-width: 180px; width: 100%; max-height: 220px; object-fit: cover; border-radius: 6px; display: block; margin: 0 auto;" />
</div>
"""
        else:
            image_html = ""

        font_style = f"font-family: {cls.FONT_FAMILY}; font-size: 14px; font-weight: 400; line-height: 1.7; color: #000000;"

        # Build Article Body
        html_parts = []
        html_parts.append(f'<div style="direction: rtl; text-align: right; {font_style}">')

        # Lead Paragraph
        if lead_paragraph:
            html_parts.append(f'<p style="{font_style} margin-bottom: 18px;">{lead_paragraph}</p>')

        # Insert Compact Image after lead paragraph if available
        if image_html:
            html_parts.append(image_html)

        # Sections
        for section in sections:
            subheading = html.escape(re.sub(r'[\*\<style>]+', '', str(section.get("subheading", "")))).strip()

            if subheading:
                html_parts.append(f'<h3 style="font-family: {cls.FONT_FAMILY} !important; color: #000000; font-size: 18px; font-weight: bold; margin-top: 22px; margin-bottom: 10px;">{subheading}</h3>')

            # Bullet List
            if section.get("is_bullet_list"):
                items = section.get("items", [])
                if items:
                    html_parts.append('<ul style="padding-right: 25px; margin-bottom: 18px; color: #000000;">')
                    for item in items:
                        formatted_item = cls._format_text_content(item, name=client_name)
                        html_parts.append(f'<li style="{font_style} margin-bottom: 6px;">{formatted_item}</li>')
                    html_parts.append('</ul>')
            else:
                # Regular Paragraphs
                paragraphs = section.get("paragraphs", [])
                for p in paragraphs:
                    formatted_p = cls._format_text_content(p, name=client_name)
                    html_parts.append(f'<p style="{font_style} margin-bottom: 16px;">{formatted_p}</p>')

        html_parts.append('</div>')

        return "\n".join(html_parts)

    @staticmethod
    def replace_image_placeholder(html_content: str, image_url: str) -> str:
        """Replaces temporary image placeholder tag or inserts image into HTML."""
        img_tag = f'<div style="text-align: center; margin: 12px 0;"><img src="{image_url}" alt="صورة الخبر" style="max-width: 180px; width: 100%; max-height: 220px; object-fit: cover; border-radius: 6px; display: block; margin: 0 auto;" /></div>'

        if "[IMAGE]" in html_content:
            return html_content.replace("[IMAGE]", img_tag)

        # If no placeholder, insert image after first paragraph
        if "</p>" in html_content:
            first_p_end = html_content.find("</p>") + 4
            return html_content[:first_p_end] + "\n" + img_tag + "\n" + html_content[first_p_end:]

        return img_tag + "\n" + html_content