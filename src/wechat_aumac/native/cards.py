"""Inspect card/quote XML delivered by the native sync path; never open URLs."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

MAX_XML_BYTES = 1024 * 1024
URL = re.compile(r"(?:https?|weixin|wxwork|wxfile)://[^\s<>\"']+", re.I)


def parse_xml(value: str) -> ET.Element:
    if not isinstance(value, str) or len(value.encode('utf-8')) > MAX_XML_BYTES:
        raise ValueError('Message XML exceeds 1 MiB')
    value=value.strip()
    if '<!DOCTYPE' in value.upper() or '<!ENTITY' in value.upper():
        raise ValueError('Message XML declarations are not allowed')
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        # The native AppMsg.Content is often a sequence of XML fragments
        # (appmsg + fromusername + scene), rather than a single document.
        fragment=re.sub(r'^<\?xml[^?]*\?>\s*','',value,count=1,flags=re.I)
        root = ET.fromstring('<message-fragments>' + fragment + '</message-fragments>')
    stack = [(root, 0)]; count = 0
    while stack:
        node, depth = stack.pop(); count += 1
        if count > 10000 or depth > 64:
            raise ValueError('Message XML exceeds node/depth limits')
        stack.extend((child, depth + 1) for child in node)
    return root


def _tag(node):
    return node.tag.rsplit('}', 1)[-1].lower()


def inspect_card(content: str) -> dict | None:
    """Return embedded links for any XML card subtype, including nested records.

    Plain text, encrypted attachments, remote-only fields and mini-program routes
    without an HTTP URL cannot yield a web URL that is absent from the payload.
    The raw message remains available to the caller for unknown card subtypes.
    """
    if not isinstance(content, str) or not content.lstrip().startswith('<'):
        return None
    root = parse_xml(content)
    app = next((n for n in root.iter() if _tag(n) == 'appmsg'), None)
    if app is None and _tag(root) not in {'msg', 'recordinfo', 'recorditem', 'location'}:
        return None
    links = []; seen = set(); routes = []; fields = {}
    remaining = MAX_XML_BYTES; nodes = 0

    def collect(value, path, level):
        nonlocal remaining
        if not value: return
        remaining -= len(value.encode('utf-8'))
        if remaining < 0: raise ValueError('Nested card data exceeds inspection budget')
        decoded = value
        # XML entities have already been decoded once by ElementTree. CDATA
        # record payloads and escaped XML sometimes need another bounded pass.
        for _ in range(3):
            next_value = re.sub(r'&(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);',
                                lambda match: html.unescape(match.group()), decoded)
            if next_value == decoded: break
            decoded = next_value
        for match in URL.finditer(decoded):
            url = match.group()
            if decoded.strip()!=url:url=url.rstrip('.,;!，。；！')
            if url not in seen:
                if len(links) >= 256: raise ValueError('Too many embedded card links')
                seen.add(url); links.append({'url': url, 'path': path})
        if level < 4 and decoded.lstrip().startswith('<'):
            try: nested = parse_xml(decoded)
            except ET.ParseError: return
            visit(nested, path + '/embedded', level + 1, 0)

    def visit(node, path, level, depth):
        nonlocal nodes
        nodes += 1
        if nodes > 10000 or depth > 64: raise ValueError('Nested card tree exceeds limits')
        path = path + '/' + _tag(node)
        collect(node.text, path, level)
        for key, value in node.attrib.items(): collect(value, path + '/@' + key, level)
        if _tag(node) == 'weappinfo':
            routes.append({key: node.findtext(key) for key in ('appid', 'username', 'pagepath')})
        for child in node:
            visit(child, path, level, depth + 1)
            collect(child.tail, path + '/tail', level)

    visit(root, '', 0, 0)
    if app is not None:
        for key in ('type', 'title', 'des', 'url', 'sourcedisplayname'):
            fields[key] = app.findtext(key)
        ref = app.find('refermsg')
        if ref is not None:
            fields['quote'] = {key: ref.findtext(key) for key in
                               ('type', 'svrid', 'fromusr', 'chatusr', 'displayname', 'content', 'msgsource')}
    return {'subtype': fields.pop('type', None), **fields, 'links': links,
            'mini_programs': routes, 'link_scope': 'embedded_payload_only'}


def enrich_message(message: dict) -> dict:
    """Keep an unsupported/malformed card as a message, with a parse error."""
    try:
        card = inspect_card(message.get('text', ''))
    except (ValueError, ET.ParseError, UnicodeError) as exc:
        message['card_error'] = str(exc)
    else:
        if card is not None:
            message['card'] = card
            message['links'] = [link['url'] for link in card['links']]
            if 'quote' in card: message['quote'] = card['quote']
    return message
