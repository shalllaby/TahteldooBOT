import html
import json
import re

class ArticleFormatter:
    """Formatter to convert AI Structured Output into clean, highly professional HTML for Blogger following TahtElDoo style and Google SEO 2026 standards."""

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
    def generate_schema_jsonld(cls, ai_data: dict, image_url: str = None) -> str:
        """
        Generates Google-compliant Schema.org JSON-LD structured data:
        - NewsArticle for Google News and search indexing.
        """
        title = ai_data.get("title", "خبر صحفي")
        meta_desc = ai_data.get("meta_description", "")
        if not meta_desc:
            lead = re.sub(r'[\*\<style>]+', '', str(ai_data.get("lead_paragraph", "")))
            meta_desc = lead[:150].strip()

        schema_graph = [
            {
                "@type": "NewsArticle",
                "headline": title,
                "description": meta_desc,
                "inLanguage": "ar",
                "publisher": {
                    "@type": "NewsMediaOrganization",
                    "name": "جريدة تحت الضوء",
                    "url": "https://tahteldoonews.blogspot.com"
                },
                "author": {
                    "@type": "Organization",
                    "name": "جريدة تحت الضوء"
                }
            }
        ]
        if image_url:
            schema_graph[0]["image"] = [image_url]



        schema_data = {
            "@context": "https://schema.org",
            "@graph": schema_graph
        }
        return f'<script type="application/ld+json">\n{json.dumps(schema_data, ensure_ascii=False, indent=2)}\n</script>'

    @classmethod
    def json_to_html(cls, ai_data: dict, image_url: str = None) -> str:
        """
        Converts structured JSON from AI into elegant, formal journalistic HTML with Google SEO 2026 standards:
        - font-family: 'Lato', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
        - font-size: 14px;
        - font-weight: 400;
        - line-height: 1.7;
        - color: #000000;
        - Semantic <h2> headings for Google Search indexing (#111827, font-weight: bold, font-size: 18px)
        - Highlighted important terms wrapped in clean <strong>...</strong> matching font family
        - Compact centered image with SEO-optimized alt & title attributes
        - Embedded Schema.org JSON-LD (NewsArticle)
        """
        raw_lead = ai_data.get("lead_paragraph", "")
        sections = ai_data.get("sections", [])
        client_name = ai_data.get("client_name", "")
        focus_kw = str(ai_data.get("focus_keyword", "")).strip()
        title = str(ai_data.get("title", "")).strip()

        # Generate Dynamic SEO Alt & Title
        if client_name and focus_kw:
            alt_text = f"{client_name} - {focus_kw} | جريدة تحت الضوء"
        elif client_name:
            alt_text = f"{client_name} | جريدة تحت الضوء الإخبارية"
        elif title:
            alt_text = f"{title} | جريدة تحت الضوء"
        else:
            alt_text = "جريدة تحت الضوء الإخبارية"
        alt_escaped = html.escape(alt_text)

        # Format lead paragraph with bolding support
        lead_paragraph = cls._format_text_content(raw_lead, name=client_name)

        # Image HTML block (Compact 180px thumbnail display with dynamic SEO alt/title)
        if image_url:
            image_html = f"""
<div style="text-align: center; margin: 14px 0;">
    <img src="{image_url}" alt="{alt_escaped}" title="{alt_escaped}" style="max-width: 180px; width: 100%; max-height: 220px; object-fit: cover; border-radius: 6px; display: block; margin: 0 auto;" />
</div>
"""
        else:
            image_html = ""

        font_style = f"font-family: {cls.FONT_FAMILY}; font-size: 14px; font-weight: 400; line-height: 1.7; color: #000000;"

        # Build Article Body
        html_parts = []

        # Meta description tag for scrapers and Blogger themes
        meta_desc = ai_data.get("meta_description", "")
        if meta_desc:
            html_parts.append(f'<meta name="description" content="{html.escape(meta_desc.strip())}" />')

        html_parts.append(f'<div style="direction: rtl; text-align: right; {font_style}">')

        # Lead Paragraph
        if lead_paragraph:
            html_parts.append(f'<p style="{font_style} margin-bottom: 18px;">{lead_paragraph}</p>')

        # Insert Compact Image after lead paragraph if available
        if image_html:
            html_parts.append(image_html)

        # Sections (Semantic <h2> for Google SEO hierarchy)
        for section in sections:
            subheading = html.escape(re.sub(r'[\*\<style>]+', '', str(section.get("subheading", "")))).strip()

            if subheading:
                html_parts.append(f'<h2 style="font-family: {cls.FONT_FAMILY} !important; color: #111827; font-size: 18px; font-weight: bold; margin-top: 24px; margin-bottom: 10px; line-height: 1.5;">{subheading}</h2>')

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

        # Inject Schema.org JSON-LD Structured Data
        schema_ld = cls.generate_schema_jsonld(ai_data, image_url=image_url)
        html_parts.append(schema_ld)

        return "\n".join(html_parts)

    @staticmethod
    def replace_image_placeholder(html_content: str, image_url: str, alt_text: str = None) -> str:
        """Replaces temporary image placeholder tag or inserts image into HTML with dynamic SEO alt text."""
        clean_alt = html.escape(alt_text.strip()) if alt_text and alt_text.strip() else "جريدة تحت الضوء الإخبارية"
        img_tag = f'<div style="text-align: center; margin: 14px 0;"><img src="{image_url}" alt="{clean_alt}" title="{clean_alt}" style="max-width: 180px; width: 100%; max-height: 220px; object-fit: cover; border-radius: 6px; display: block; margin: 0 auto;" /></div>'

        if "[IMAGE]" in html_content:
            return html_content.replace("[IMAGE]", img_tag)

        # If no placeholder, insert image after first paragraph
        if "</p>" in html_content:
            first_p_end = html_content.find("</p>") + 4
            return html_content[:first_p_end] + "\n" + img_tag + "\n" + html_content[first_p_end:]

        return img_tag + "\n" + html_content

    # Alias for web_server and API compatibility
    format_full_article = json_to_html