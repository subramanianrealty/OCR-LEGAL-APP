# -*- coding: utf-8 -*-
"""
Dedicated Sale Deed / Title Deed (கிரையப் பத்திரம்) Extractor.
Extracts:
- Executant/Vendor & Claimant/Purchaser: name, father's/husband's name, address (with DPDP Masked Aadhaar & PAN)
- History & Previous Owner / Mother Deed Reference
- Schedule of Property (Land, Land with Building, Apartment UDS, Built-Up Area, Flat No & Floor)
- Survey Number & Sub-division (isolated)
- Village / Taluk / District
- Boundaries (combined N/S/E/W and per-direction)
- Land Classification (Wet/Dry/House Site/Nanjai/Punjai)
- Consideration Amount, Document Number, Book Number, Registration Date, SRO
- Witnesses, Registrar's Endorsement/Seal
- NRI Passport & Visa details (if either party is an NRI)
- Registered Power of Attorney details (if signed on behalf of the owner)

Tamil OCR text is worked on directly using the local bilingual translation layer
(app.translator: dictionary lookup + local IndicTrans2 neural model) so no
document content is ever sent to an external translation service.
"""

import re
from typing import Dict, Any, List, Optional
from app.translator import format_bilingual_entity
from app.validator import ExtractionValidator


class SaleDeedExtractor:
    """Extractor for Sale Deed / Title Deed."""

    def __init__(self):
        pass

    def _find_value(self, text, patterns, flags=re.IGNORECASE):
        for pat in patterns:
            m = re.search(pat, text, flags)
            if m:
                return m.group(1).strip()
        return None

    def _extract_block(self, text: str, start_patterns: List[str]) -> Optional[str]:
        """
        Returns the text following a section header (e.g. 'VENDOR DETAILS:' / 'விற்பவர் விவரம்:')
        up to the next numbered section header or a blank-line gap.
        """
        for sp in start_patterns:
            m = re.search(sp, text, re.IGNORECASE)
            if m:
                rest = text[m.end():]
                # Cut at the first blank-line gap (sections/list-blocks in these deeds are
                # blank-line separated; a plain "\n" between numbered witness lines must NOT
                # be treated as a new section boundary).
                end_m = re.search(r'\n\s*\n', rest)
                block = rest[:end_m.start()] if end_m else rest[:800]
                return block.strip()
        return None

    def _extract_person_block(self, block: Optional[str]) -> Dict[str, Any]:
        """Extracts name, father's/husband's name, address, PAN, masked Aadhaar, NRI & POA hints from a party block."""
        info: Dict[str, Any] = {}
        if not block:
            return info

        name_m = re.search(r'(?:Name|பெயர்)\s*[:\-]\s*([^\n]+)', block, re.IGNORECASE)
        name_line = name_m.group(1).strip() if name_m else block.splitlines()[0].strip()

        rel_m = re.search(
            r'^(.*?),?\s*(?:S/o|W/o|D/o|H/o|Son of|Wife of|Daughter of|Husband of|'
            r'மகன்|மனைவி|மகள்|கணவர்|தந்தை|த/பெ|க/பெ)\s*(?:பெயர்)?\.?\s*'
            r'(?:Late\s+)?([^\n,]+)',
            name_line, re.IGNORECASE
        )
        if rel_m:
            info["name"] = rel_m.group(1).strip().rstrip(',')
            info["relation_name"] = rel_m.group(2).strip()
        else:
            # Drop a trailing "rep by ... Power of Attorney ..." clause so it isn't
            # mistaken for part of the party's own name.
            name_only = re.split(r',?\s*(?:rep\.?\s*by|represented\s*by|through)\b', name_line, flags=re.IGNORECASE)[0]
            info["name"] = name_only.strip().rstrip(',')

        addr_m = re.search(r'(?:Address|முகவரி)\s*[:\-]\s*([^\n]+)', block, re.IGNORECASE)
        if addr_m:
            info["address"] = addr_m.group(1).strip()

        pan_m = re.search(r'\b([A-Z]{5}\d{4}[A-Z])\b', block)
        if pan_m:
            info["pan"] = pan_m.group(1)

        aad_m = re.search(r'(XXXX[\s-]*XXXX[\s-]*\d{4})', block, re.IGNORECASE) or re.search(r'(\d{4}[\s-]*\d{4}[\s-]*\d{4})', block)
        if aad_m:
            info["aadhaar"] = ExtractionValidator.enforce_dpdp_masking(aad_m.group(1))

        # NRI Passport / Visa details
        pass_m = re.search(r'Passport\s*(?:No\.?|Number)?\s*[:\-]\s*([A-Za-z0-9]+)', block, re.IGNORECASE)
        visa_m = re.search(r'Visa\s*(?:No\.?|Type|Details)?\s*[:\-]\s*([^\n]+)', block, re.IGNORECASE)
        is_nri = bool(pass_m or visa_m) or bool(re.search(r'\bNRI\b|non[\s\-]?resident\s*indian', block, re.IGNORECASE))
        if is_nri:
            parts = []
            if pass_m:
                parts.append(f"Passport No: {pass_m.group(1)}")
            if visa_m:
                parts.append(f"Visa: {visa_m.group(1).strip()}")
            info["nri_passport_visa"] = " | ".join(parts) if parts else "NRI party indicated — Passport/Visa number not detected in text"

        # Registered Power of Attorney reference
        poa_m = re.search(
            r'(?:rep\.?\s*by|represented\s*by|through)\s*(?:her|his)?\s*(?:registered\s*)?'
            r'(?:power\s*of\s*attorney|POA|GPA|General\s*Power\s*of\s*Attorney|அதிகாரப்பத்திரம்)[^\n]*',
            block, re.IGNORECASE
        )
        if poa_m:
            info["poa"] = poa_m.group(0).strip()
        elif re.search(r'\bPOA\b|\bGPA\b|power\s*of\s*attorney|அதிகாரப்பத்திரம்', block, re.IGNORECASE):
            info["poa"] = "Registered Power of Attorney referenced in this section"

        return info

    def _extract_recital_party(self, text: str, role_terms: List[str]) -> Dict[str, Any]:
        """
        Extracts a party's name/relation/address/POA from flowing legal prose of the form:
            "...by Mr. X Son of Y residing at Z ... represented by his duly constituted
             (General) Power of Attorney Mr. A Son of B residing at C (... dated D and
             registered as Document No E of Year F of Book G at the office of the
             Sub Registrar of H) hereinafter called the 'VENDOR' ..."
        Used for typed/prose sale deeds that don't use a "VENDOR DETAILS:" label block.
        """
        info: Dict[str, Any] = {}
        role_pattern = "|".join(role_terms)
        anchor_m = re.search(
            rf"hereinafter\s+(?:referred\s+to\s+as|called)\s+(?:the\s+)?['\"]?(?:{role_pattern})['\"]?",
            text, re.IGNORECASE
        )
        if not anchor_m:
            return info

        window = text[max(0, anchor_m.start() - 900):anchor_m.start()]

        name_m = re.search(r'(?:Mr\.|Mrs\.|Ms\.|Thiru\.|Smt\.|Selvi\.)\s*([A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*)*)', window)
        if not name_m:
            return info

        sub_window = window[name_m.end():name_m.end() + 350]
        info["name"] = name_m.group(1).strip()

        rel_m = re.search(
            r'(?:S/o|W/o|D/o|H/o|Son of|Wife of|Daughter of|Husband of)\s+(?:Late\s+)?([A-Za-z.\s]+?)(?=\s+resid|,|\()',
            sub_window, re.IGNORECASE
        )
        if rel_m:
            info["relation_name"] = re.sub(r'\s+', ' ', rel_m.group(1)).strip()

        addr_m = re.search(
            r'resid(?:ing|ent)\s+at\s+([^()]+?)(?:\s*\(|,?\s*represented\s+by|,?\s*hereinafter|$)',
            sub_window, re.IGNORECASE
        )
        if addr_m:
            info["address"] = re.sub(r'\s+', ' ', addr_m.group(1)).strip().rstrip(',')

        # Power of Attorney representation, if present in this party's recital block
        poa_name_m = re.search(
            r'represented\s+by\s+(?:his|her|their)?\s*duly\s+constituted\s+(?:General\s+)?Power\s+of\s+Attorney\s+'
            r'(?:Mr\.|Mrs\.|Ms\.)?\s*([A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*)*)',
            window, re.IGNORECASE
        )
        if poa_name_m:
            poa_sub_window = window[poa_name_m.end():poa_name_m.end() + 350]
            poa_rel_m = re.search(
                r'(?:S/o|W/o|D/o|Son of|Wife of|Daughter of)\s+(?:Mr\.|Mrs\.)?\s*(?:Late\s+)?([A-Za-z.\s]+?)(?=\s+resid|,|\()',
                poa_sub_window, re.IGNORECASE
            )
            poa_addr_m = re.search(
                r'resid(?:ing|ent)\s+at\s+([^()]+?)(?:\s*\(|,?\s*hereinafter|$)',
                poa_sub_window, re.IGNORECASE
            )
            poa_reg_m = re.search(
                r'dated\s+([\d.\-/]+)\s+and\s+registered\s+as\s+Document\s+No\.?\s*(\d+)\s+of\s+(\d{4})\s+of\s+Book\s+(\d+)'
                r'[^)]*?Sub\s*[- ]?Registrar\s+of\s+([A-Za-z]+)',
                window, re.IGNORECASE
            )
            poa_parts = [f"Power of Attorney holder: {poa_name_m.group(1).strip()}"]
            if poa_rel_m:
                poa_rel_clean = re.sub(r'\s+', ' ', poa_rel_m.group(1)).strip()
                poa_parts.append(f"(S/o or W/o {poa_rel_clean})")
            if poa_addr_m:
                poa_addr_clean = re.sub(r'\s+', ' ', poa_addr_m.group(1)).strip().rstrip(',')
                poa_parts.append(f"residing at {poa_addr_clean}")
            if poa_reg_m:
                poa_parts.append(
                    f"— GPA dated {poa_reg_m.group(1)}, registered as Document No {poa_reg_m.group(2)}/{poa_reg_m.group(3)}, "
                    f"Book {poa_reg_m.group(4)}, SRO {poa_reg_m.group(5)}"
                )
            info["poa"] = " ".join(poa_parts)

        return info

    def _extract_name_near_label(self, text: str, label_patterns: List[str], search_window: int = 400) -> Optional[str]:
        """
        Last-resort fallback for signature-block layouts: finds a bare party label
        line (e.g. "Purchaser" on its own line, common in scanned execution blocks)
        and returns the first following line that looks like a person's name.
        """
        for lp in label_patterns:
            for m in re.finditer(lp, text, re.IGNORECASE | re.MULTILINE):
                forward = text[m.end():m.end() + search_window]
                for line in forward.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if re.match(r'^[A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+){1,3}$', line):
                        return line
        return None

    def extract(self, text: str) -> Dict[str, Any]:
        fields = {}

        # ── Block-scoped extraction for Vendor / Purchaser (keeps addresses & PAN from bleeding across parties) ──
        vendor_block = self._extract_block(text, [
            r'(?:\d+\.\s*)?VENDOR\s*DETAILS?\s*:?',
            r'(?:\d+\.\s*)?(?:EXECUTANT|SELLER)[^\n]*:?',
            r'(?:\d+\.\s*)?விற்பவர்(?:\s*விவரம்)?\s*:?',
            r'(?:\d+\.\s*)?எழுதிக்\s*கொடுத்தவர்[^\n]*:?',
        ])
        purchaser_block = self._extract_block(text, [
            r'(?:\d+\.\s*)?PURCHASER\s*DETAILS?\s*:?',
            r'(?:\d+\.\s*)?(?:CLAIMANT|BUYER)[^\n]*:?',
            r'(?:\d+\.\s*)?வாங்குபவர்(?:\s*விவரம்)?\s*:?',
            r'(?:\d+\.\s*)?எழுதி\s*வாங்கியவர்[^\n]*:?',
        ])
        vendor_info = self._extract_person_block(vendor_block)
        purchaser_info = self._extract_person_block(purchaser_block)

        # Confidence multiplier reflecting which extraction strategy succeeded:
        # 1.0 = structured "Name:/Address:" block, 0.90 = flowing legal recital
        # ("...hereinafter called the VENDOR..."), 0.65 = last-resort label+
        # signature-block name scan (used on typed prose deeds and scanned
        # execution/signature blocks where no clean labeled section exists).
        vendor_conf = 1.0
        purchaser_conf = 1.0

        if not vendor_info.get("name"):
            recital = self._extract_recital_party(text, ["VENDOR", "EXECUTANT", "SELLER"])
            if recital.get("name"):
                vendor_info = recital
                vendor_conf = 0.90

        if not purchaser_info.get("name"):
            recital = self._extract_recital_party(text, ["PURCHASER", "CLAIMANT", "BUYER"])
            if recital.get("name"):
                purchaser_info = recital
                purchaser_conf = 0.90

        if not vendor_info.get("name"):
            label_name = self._extract_name_near_label(text, [r'^\s*Vendor\b[^\n]*$', r'^\s*விற்பவர்\s*$'])
            if label_name:
                vendor_info["name"] = label_name
                vendor_conf = 0.65

        if not purchaser_info.get("name"):
            label_name = self._extract_name_near_label(text, [r'^\s*Purchaser\b[^\n]*$', r'^\s*வாங்குபவர்\s*$'])
            if label_name:
                purchaser_info["name"] = label_name
                purchaser_conf = 0.65

        # 1. Executant / Seller / Vendor (combined summary — kept for backward compatibility)
        vendor = self._find_value(text, [
            r'(?:விற்பவர்|vendor|seller|executant)[^\n:]*[ \t:]+([^\n]+)',
        ])
        vendor_summary_parts = []
        if vendor_info.get("name"):
            vendor_summary_parts.append(vendor_info["name"])
        elif vendor:
            vendor_summary_parts.append(vendor)
        if vendor_info.get("relation_name"):
            vendor_summary_parts.append(f"(S/o or W/o {vendor_info['relation_name']})")
        if vendor_info.get("pan"):
            vendor_summary_parts.append(f"PAN: {vendor_info['pan']}")
        if vendor_info.get("aadhaar"):
            vendor_summary_parts.append(f"Masked Aadhaar: {vendor_info['aadhaar']}")
        vendor_summary = " | ".join(vendor_summary_parts) if vendor_summary_parts else vendor
        fields["vendor_details"] = {
            "value": vendor_summary or "Not Detected",
            "confidence": round(0.95 * vendor_conf, 2) if vendor_summary else 0.0,
            "label": "விற்பவர் விவரம் (Vendor / Executant Details)",
            "box_query": vendor_info.get("name") or vendor,
        }

        # 1a. Vendor name / father-husband name / address (isolated fields)
        fields["vendor_name"] = {
            "value": vendor_info.get("name") or vendor or "Not Detected",
            "confidence": round(0.94 * vendor_conf, 2) if (vendor_info.get("name") or vendor) else 0.0,
            "label": "விற்பவர் பெயர் (Executant / Seller Name)",
            "box_query": vendor_info.get("name") or vendor,
        }
        fields["vendor_father_husband_name"] = {
            "value": vendor_info.get("relation_name") or "Not Detected",
            "confidence": round(0.90 * vendor_conf, 2) if vendor_info.get("relation_name") else 0.0,
            "label": "தந்தை / கணவர் பெயர் (Vendor's Father's / Husband's Name)",
        }
        fields["vendor_address"] = {
            "value": vendor_info.get("address") or "Not Detected",
            "confidence": round(0.92 * vendor_conf, 2) if vendor_info.get("address") else 0.0,
            "label": "விற்பவர் முகவரி (Vendor Address)",
        }

        # 2. Purchaser / Buyer / Claimant (combined summary — kept for backward compatibility)
        purchaser = self._find_value(text, [
            r'(?:வாங்குபவர்|purchaser|buyer|claimant)[^\n:]*[ \t:]+([^\n]+)',
        ])
        purchaser_summary_parts = []
        if purchaser_info.get("name"):
            purchaser_summary_parts.append(purchaser_info["name"])
        elif purchaser:
            purchaser_summary_parts.append(purchaser)
        if purchaser_info.get("relation_name"):
            purchaser_summary_parts.append(f"(S/o or W/o {purchaser_info['relation_name']})")
        if purchaser_info.get("pan"):
            purchaser_summary_parts.append(f"PAN: {purchaser_info['pan']}")
        if purchaser_info.get("aadhaar"):
            purchaser_summary_parts.append(f"Masked Aadhaar: {purchaser_info['aadhaar']}")
        purchaser_summary = " | ".join(purchaser_summary_parts) if purchaser_summary_parts else purchaser
        fields["purchaser_details"] = {
            "value": purchaser_summary or "Not Detected",
            "confidence": round(0.95 * purchaser_conf, 2) if purchaser_summary else 0.0,
            "label": "வாங்குபவர் விவரம் (Purchaser / Claimant Details)",
            "box_query": purchaser_info.get("name") or purchaser,
        }

        # 2a. Purchaser name / father-husband name / address (isolated fields)
        fields["purchaser_name"] = {
            "value": purchaser_info.get("name") or purchaser or "Not Detected",
            "confidence": round(0.94 * purchaser_conf, 2) if (purchaser_info.get("name") or purchaser) else 0.0,
            "label": "வாங்குபவர் பெயர் (Purchaser / Claimant Name)",
            "box_query": purchaser_info.get("name") or purchaser,
        }
        fields["purchaser_father_husband_name"] = {
            "value": purchaser_info.get("relation_name") or "Not Detected",
            "confidence": round(0.90 * purchaser_conf, 2) if purchaser_info.get("relation_name") else 0.0,
            "label": "தந்தை / கணவர் பெயர் (Purchaser's Father's / Husband's Name)",
        }
        fields["purchaser_address"] = {
            "value": purchaser_info.get("address") or "Not Detected",
            "confidence": round(0.92 * purchaser_conf, 2) if purchaser_info.get("address") else 0.0,
            "label": "வாங்குபவர் முகவரி (Purchaser Address)",
        }

        # 3. Previous Owner / Mother Deed Reference
        # Scoped to the "History / Previous Owner" section block so a bare mention of
        # "PREVIOUS OWNER" inside that section's own heading is never mistaken for the value.
        history_block = self._extract_block(text, [
            r'(?:\d+\.\s*)?HISTORY\s*/?\s*PREVIOUS\s*OWNER\s*DETAILS?\s*:?',
            r'(?:\d+\.\s*)?முந்தைய\s*உரிமையாளர்(?:\s*விவரம்)?\s*:?',
        ])
        history_scope = history_block or text

        prev_owner = self._find_value(history_scope, [
            r'(?:முந்தைய\s*உரிமையாளர்|previous\s*owner|prior\s*deed|mother\s*deed|parent\s*deed)[^\n:]*:[ \t]*([^\n]+)',
        ])
        fields["history_previous_owner"] = {
            "value": prev_owner or "Not Detected",
            "confidence": 0.92 if prev_owner else 0.0,
            "label": "முந்தைய உரிமையாளர் (Previous Owner / History)",
            "box_query": prev_owner,
        }

        prev_doc_ref = self._find_value(history_scope, [
            r'(?:முந்தைய\s*ஆவணம்|previous\s*document|prior\s*doc\s*ref(?:erence)?|parent\s*doc\s*no)[^\n:]*:[ \t]*([^\n]+)',
            r'(?:Doc(?:ument)?\s*No\.?\s*([\d\s]+/[\d\s]+)[^\n]*registered)',
        ])
        fields["previous_doc_reference"] = {
            "value": prev_doc_ref or "Not Detected",
            "confidence": 0.91 if prev_doc_ref else 0.0,
            "label": "முந்தைய ஆவணக் குறிப்பு (Previous Document Reference)",
            "box_query": prev_doc_ref,
        }

        # 4. Schedule of Property Breakdown (Land, Building, Apartment UDS)
        is_apartment = any(k in text.lower() for k in ["flat", "apartment", "uds", "undivided share", "குடியிருப்பு"])
        is_building = any(k in text.lower() for k in ["building", "built up", "built-up", "house", "வீடு", "கட்டிடம்"])
        prop_type = "Apartment / Flat (UDS + Built-up)" if is_apartment else (
            "Land with Building" if is_building else "Land / Plot"
        )
        fields["schedule_property_type"] = {
            "value": prop_type,
            "confidence": 0.90,
            "label": "சொத்து விவரம் (Schedule of Property)",
        }

        # 5. Survey Number & Sub-division (isolated)
        survey = self._find_value(text, [
            r'(?:புல\s*எண்|survey|\bsy\b|\bt\.?s\.?\b)\s*(?:no\.?|number)?[^\n:]*:[ \t]*([0-9A-Za-z/,.()\t -]+)',
            r'\b(\d{1,4}\s*[-/]\s*\d{1,3}[A-Za-z]?)\b',
        ])
        fields["survey_number"] = {
            "value": survey or "Not Detected",
            "confidence": 0.94 if survey else 0.0,
            "label": "புல எண் (Survey Number / S.No)",
            "box_query": survey,
        }

        sub_division = self._find_value(text, [
            r'(?:உட்பிரிவு|sub[\s-]?division(?:\s*no\.?)?)[^\n:]*[ \t:]+([0-9A-Za-z,/\s]+)',
        ])
        if not sub_division and survey:
            sd_m = re.search(r'\d+\s*/\s*([0-9]+[A-Za-z]?)', survey)
            if sd_m:
                sub_division = sd_m.group(1)
        fields["sub_division_number"] = {
            "value": sub_division or "Not Detected",
            "confidence": 0.88 if sub_division else 0.0,
            "label": "உட்பிரிவு எண் (Sub-division Number)",
        }

        # 6. Village / Taluk / District (with Bilingual Layer)
        dist_m = re.search(r'(?:District|மாவட்டம்)\s*[ \t:]+([^\n:|]+)', text, re.IGNORECASE)
        tal_m = re.search(r'(?:Taluk|வட்டம்)\s*[ \t:]+([^\n:|]+)', text, re.IGNORECASE)
        vil_m = re.search(r'(?:Village|கிராமம்)\s*[ \t:]+([^\n:|]+)', text, re.IGNORECASE)

        v_parts = []
        if vil_m:
            v_parts.append(format_bilingual_entity(vil_m.group(1).strip()))
        if tal_m:
            v_parts.append(format_bilingual_entity(tal_m.group(1).strip()))
        if dist_m:
            v_parts.append(format_bilingual_entity(dist_m.group(1).strip()))

        vtd = " / ".join(v_parts) if v_parts else None

        fields["village_taluk_district"] = {
            "value": vtd or "Not Detected",
            "confidence": 0.92 if vtd else 0.0,
            "label": "கிராமம் / வட்டம் / மாவட்டம் (Village / Taluk / District)",
            "box_query": "மாவட்டம் | வட்டம் | கிராமம்",
        }

        # 7. Land Extent
        extent = self._find_value(text, [
            r'(?:பரப்பு|extent|area)[^\n:]*[ \t:]+([^\n]+)',
            r'([0-9.]+\s*(?:sq\.?\s*ft|cents?|acres?|grounds?|ஏர்|ares|hectare))',
        ])
        fields["land_extent"] = {
            "value": extent or "Not Detected",
            "confidence": 0.92 if extent else 0.0,
            "label": "பரப்பு (Land Extent)",
            "box_query": extent,
        }

        # 8. Building / UDS / Flat (isolated sub-fields + combined summary)
        flat_no = self._find_value(text, [
            r'(?:Flat\s*No\.?|Door\s*No\.?|தட்டு\s*எண்|கதவு\s*எண்)\s*[:\-\s]+([A-Za-z0-9\-/]+)',
        ])
        floor_no = self._find_value(text, [
            r'((?:Ground|First|Second|Third|Fourth|Fifth|\d+(?:st|nd|rd|th))\s*Floor)',
            r'(?:மாடி|தளம்)\s*[:\-\s]+([^\n,|]+)',
        ])
        built_up_area = self._find_value(text, [
            r'(?:Built[\s-]?up\s*Area)[^\n:]*[ \t:]+([0-9,.]+\s*(?:sq\.?\s*ft|sq\.?\s*m|sq\.?\s*meters?)?)',
            r'(?:கட்டிடப்\s*பரப்பு)[^\n:]*[ \t:]+([^\n,|]+)',
        ])
        uds_area = self._find_value(text, [
            r'(?:UDS|Undivided\s*Share(?:\s*of\s*Land)?|பிரிக்கப்படா\s*பங்கு)[^\n:]*[ \t:]+([0-9,.]+\s*(?:sq\.?\s*ft|sq\.?\s*m)?)',
        ])

        fields["flat_number"] = {
            "value": flat_no or "Not Detected",
            "confidence": 0.90 if flat_no else 0.0,
            "label": "தட்டு எண் (Flat / Door Number)",
        }
        fields["floor_number"] = {
            "value": floor_no or "Not Detected",
            "confidence": 0.88 if floor_no else 0.0,
            "label": "மாடி எண் (Floor Number)",
        }
        fields["built_up_area"] = {
            "value": built_up_area or "Not Detected",
            "confidence": 0.90 if built_up_area else 0.0,
            "label": "கட்டிடப் பரப்பு (Built-Up Area)",
        }
        fields["uds_area"] = {
            "value": uds_area or "Not Detected",
            "confidence": 0.90 if uds_area else 0.0,
            "label": "பிரிக்கப்படா பங்கு (Undivided Share of Land - UDS)",
        }
        fields["building_built_up_area"] = {
            "value": (
                f"Built-Up Area: {built_up_area}" if built_up_area and not is_apartment
                else (built_up_area or "Not Detected")
            ),
            "confidence": 0.88 if (built_up_area and is_building) else 0.0,
            "label": "நிலம் + கட்டிடப் பரப்பு (Land with Building - Built-Up Area)",
        }

        uds_combo_parts = []
        if flat_no:
            uds_combo_parts.append(f"Flat No. {flat_no}")
        if floor_no:
            uds_combo_parts.append(floor_no)
        if built_up_area:
            uds_combo_parts.append(f"Built-Up Area: {built_up_area}")
        if uds_area:
            uds_combo_parts.append(f"UDS: {uds_area}")
        uds_combined = " | ".join(uds_combo_parts) if uds_combo_parts else self._find_value(text, [
            r'(?:undivided share|uds|பிரிக்கப்படா பங்கு)[^\n:]*[ \t:]+([^\n]+)',
        ])
        fields["apartment_uds_floor"] = {
            "value": uds_combined or "Not Detected",
            "confidence": 0.90 if uds_combined else 0.0,
            "label": "பிரிக்கப்படா பங்கு / மாடி (UDS / Built-up / Floor)",
        }

        # 9. Boundaries — combined + per-direction
        b_match = re.search(r'(?:boundar(?:y|ies)|எல்லைகள்)[^\n:]*:[ \t]*([^\n]+(?:\n[^\n]+){1,4})', text, re.IGNORECASE)
        boundaries = b_match.group(1).strip() if b_match else None

        direction_map = [
            ("boundary_north", ["வடக்கு", "வடக்கில்"], ["north"], "வடக்கு எல்லை (North Boundary)"),
            ("boundary_south", ["தெற்கு", "தெற்கில்"], ["south"], "தெற்கு எல்லை (South Boundary)"),
            ("boundary_east", ["கிழக்கு", "கிழக்கில்"], ["east"], "கிழக்கு எல்லை (East Boundary)"),
            ("boundary_west", ["மேற்கு", "மேற்கில்"], ["west"], "மேற்கு எல்லை (West Boundary)"),
        ]
        for field_key, ta_terms, en_terms, label in direction_map:
            terms = "|".join(ta_terms + en_terms)
            val = self._find_value(text, [
                rf'(?:{terms})\s*(?:எல்லை|boundary|by|side)?\s*[:\-]\s*([^\n]+)',
                rf'(?:{terms})\s*by\s*[:\-]?\s*([^\n]+)',
            ])
            fields[field_key] = {
                "value": val or "Not Detected",
                "confidence": 0.88 if val else 0.0,
                "label": label,
            }

        if not boundaries:
            per_dir_parts = [
                f"{d[3].split('(')[1].rstrip(')')}: {fields[d[0]]['value']}"
                for d in direction_map if fields[d[0]]["value"] != "Not Detected"
            ]
            boundaries = " | ".join(per_dir_parts) if per_dir_parts else None
        fields["boundaries"] = {
            "value": boundaries or "Not Detected",
            "confidence": 0.90 if boundaries else 0.0,
            "label": "எல்லைகள் (Boundaries N/S/E/W)",
        }

        # 10. Land Classification
        classification = self._find_value(text, [
            r'(?:classification|நில வகைப்பாடு|வகை)[^\n:]*[ \t:]+([^\n]+)',
            r'\b(நஞ்சை|புஞ்சை|மனை|house\s*site|wet\s*land|dry\s*land|agricultural|residential)\b',
        ])
        fields["land_classification"] = {
            "value": classification or "House Site / Residential",
            "confidence": 0.90 if classification else 0.85,
            "label": "நில வகைப்பாடு (Classification - Wet/Dry/House Site)",
        }

        # 11. SRO Details
        sro = self._find_value(text, [
            r'(?:sub.?registrar|\bsro\b|பதிவாளர்|பதிவு அலுவலகம்)[^\n:]*:[ \t]*([^\n|]+)',
        ])
        fields["sro_details"] = {
            "value": sro or "Not Detected",
            "confidence": 0.92 if sro else 0.0,
            "label": "பதிவாளர் அலுவலகம் (SRO Details)",
            "box_query": sro,
        }

        # 12. Document Number, Book Number & Registration Date
        doc_no = self._find_value(text, [
            r'(?:ஆவண எண்|document\s*no|doc\.?\s*no)[^\n:]*:[ \t]*([^\n|]+)',
        ])
        fields["document_number"] = {
            "value": doc_no or "Not Detected",
            "confidence": 0.92 if doc_no else 0.0,
            "label": "ஆவண எண் (Document Number)",
            "box_query": doc_no,
        }

        book_no = self._find_value(text, [
            r'(?:Book\s*(?:No\.?)?|புத்தகம்(?:\s*எண்)?)\s*[:\-]?\s*(\d+[A-Za-z]?)',
        ])
        fields["book_number"] = {
            "value": book_no or "Not Detected",
            "confidence": 0.90 if book_no else 0.0,
            "label": "புத்தகம் எண் (Book Number)",
        }

        reg_date = self._find_value(text, [
            r'(?:பதிவு நாள்|registration\s*date|date\s*of\s*reg)[^\n:]*[ \t:]+([^\n]+)',
            r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
        ])
        fields["registration_date"] = {
            "value": reg_date or "Not Detected",
            "confidence": 0.90 if reg_date else 0.0,
            "label": "பதிவு நாள் (Registration Date)",
            "box_query": reg_date,
        }

        # 13. Consideration Amount
        amt = self._find_value(text, [
            r'(?:கிரையத்\s*தொகை|consideration|sale\s*value|sale\s*price)[^\n:]*[ \t:]+([^\n]+)',
            r'(?:rs\.?|inr|₹)\s*([\d,]+)',
        ])
        fields["consideration_amount"] = {
            "value": amt or "Not Detected",
            "confidence": 0.93 if amt else 0.0,
            "label": "கிரையத் தொகை (Consideration Amount)",
            "box_query": amt,
        }

        # 14. Witnesses
        wit_block = self._extract_block(text, [
            r'(?:\d+\.\s*)?WITNESS(?:ES)?\s*:?',
            r'(?:\d+\.\s*)?சாட்சி(?:கள்)?\s*(?:விவரம்)?\s*:?',
        ])
        witnesses = None
        if wit_block:
            wit_lines = [
                re.sub(r'^\d+[\.\)]\s*', '', ln.strip())
                for ln in wit_block.splitlines() if ln.strip()
            ]
            wit_lines = [ln for ln in wit_lines if len(ln) >= 2][:4]
            if wit_lines:
                witnesses = ", ".join(wit_lines)
        if not witnesses:
            witnesses = self._find_value(text, [
                r'(?:Witness(?:es)?|சாட்சி(?:கள்)?)\s*(?:Name\(s\)?)?\s*[:\-]\s*([^\n]+)',
            ])
        fields["witnesses"] = {
            "value": witnesses or "Not Detected",
            "confidence": 0.88 if witnesses else 0.0,
            "label": "சாட்சிகள் (Witnesses' Names & Signatures)",
        }

        # 15. Registrar's Endorsement / Seal
        has_endorsement = bool(re.search(
            r'endorsement|office\s*seal|seal\s*of\s*the\s*sub[\s-]?registrar|certified\s*that\s*this\s*document|'
            r'presented\s*for\s*registration|பதிவாளர்\s*(?:ஒப்பம்|சான்று|முத்திரை)|சான்று\s*செய்யப்பட்டது',
            text, re.IGNORECASE
        ))
        fields["registrar_endorsement"] = {
            "value": "Registrar's Endorsement / Office Seal detected in document" if has_endorsement else "Not Detected",
            "confidence": 0.85 if has_endorsement else 0.0,
            "label": "பதிவாளர் சான்று / முத்திரை (Registrar's Endorsement / Seal)",
            "no_box": True,
        }

        # 16. NRI Passport & Visa Details (either party)
        nri_parts = []
        if vendor_info.get("nri_passport_visa"):
            nri_parts.append(f"Vendor — {vendor_info['nri_passport_visa']}")
        if purchaser_info.get("nri_passport_visa"):
            nri_parts.append(f"Purchaser — {purchaser_info['nri_passport_visa']}")
        nri_value = " || ".join(nri_parts) if nri_parts else "Not Applicable (No NRI Party Identified)"
        fields["nri_passport_visa_details"] = {
            "value": nri_value,
            "confidence": 0.90 if nri_parts else 0.75,
            "label": "பாஸ்போர்ட் / விசா விவரம் (NRI Passport & Visa Details)",
            "no_box": True,
        }

        # 17. Registered Power of Attorney Details
        poa_parts = []
        if vendor_info.get("poa"):
            poa_parts.append(f"Vendor side — {vendor_info['poa']}")
        if purchaser_info.get("poa"):
            poa_parts.append(f"Purchaser side — {purchaser_info['poa']}")
        if not poa_parts:
            generic_poa = self._find_value(text, [
                r'([^\n]*(?:registered\s*)?power\s*of\s*attorney[^\n]*)',
                r'([^\n]*அதிகாரப்பத்திரம்[^\n]*)',
            ])
            if generic_poa:
                poa_parts.append(generic_poa)
        poa_value = " || ".join(poa_parts) if poa_parts else "Not Applicable (No Power of Attorney Referenced)"
        fields["poa_details"] = {
            "value": poa_value,
            "confidence": 0.88 if poa_parts else 0.75,
            "label": "பதிவு செய்யப்பட்ட அதிகாரப்பத்திரம் (Registered Power of Attorney Details)",
            "no_box": True,
        }

        # 18. DPDP Masked Aadhaar (Last 4 digits only)
        aadhaar_raw = vendor_info.get("aadhaar") or purchaser_info.get("aadhaar") or self._find_value(text, [
            r'(?:aadhaar|ஆதார்)[^\n:]*[ \t:]+([^\n]+)',
            r'([X\d]{4}[\s-]*[X\d]{4}[\s-]*\d{4})',
        ])
        masked_aadhaar = ExtractionValidator.enforce_dpdp_masking(aadhaar_raw) if aadhaar_raw else "Not Detected"
        fields["masked_aadhaar"] = {
            "value": masked_aadhaar,
            "confidence": 0.92 if masked_aadhaar != "Not Detected" else 0.0,
            "label": "ஆதார் (DPDP Masked Aadhaar - Last 4 Digits)",
        }

        # 19. PAN Number
        pan = vendor_info.get("pan") or purchaser_info.get("pan") or self._find_value(text, [
            r'(?:pan|பான்)[^\n:]*[ \t:]+([A-Z]{5}\d{4}[A-Z])',
            r'\b([A-Z]{5}\d{4}[A-Z])\b',
        ])
        fields["pan_number"] = {
            "value": pan or "Not Detected",
            "confidence": 0.94 if pan else 0.0,
            "label": "பான் எண் (PAN Number)",
        }

        return fields
