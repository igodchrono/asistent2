# command_parser.py
import re
from typing import List, Dict, Any


class CommandParser:
    """
    Парсит ответ ассистента и извлекает все команды в структурированном виде.
    """
    
    # Регулярные выражения для команд
    PATTERNS = {
        'SEARCH': re.compile(r'\[SEARCH\s+(.+?)\]', re.IGNORECASE),
        'LAUNCH': re.compile(r'\[LAUNCH\s+(.+?)\]', re.IGNORECASE),
        'OPEN': re.compile(r'\[OPEN[:\s]+(.+?)\]', re.IGNORECASE),
        'RUN': re.compile(r'\[RUN\s+(.+?)\]', re.IGNORECASE),
        'WRITE': re.compile(r'\[WRITE\s+([^\]]+)\]\s*(.*?)\s*\[/WRITE\]', re.IGNORECASE | re.DOTALL),
        'NOTEPAD': re.compile(r'\[NOTEPAD\]\s*(.*?)\s*\[/NOTEPAD\]', re.IGNORECASE | re.DOTALL),
        'MINIMIZE': re.compile(r'\[MINIMIZE\s+(.+?)\]', re.IGNORECASE),
        'MAXIMIZE': re.compile(r'\[MAXIMIZE\s+(.+?)\]', re.IGNORECASE),
        'SWITCH': re.compile(r'\[SWITCH TO\s+(.+?)\]', re.IGNORECASE),
        'CLOSE_WINDOW': re.compile(r'\[CLOSE_WINDOW_BY_TITLE\s+(.+?)\]', re.IGNORECASE),
        'CLOSE_TAB': re.compile(r'\[CLOSE[_ ]TABS?(?:\s+(\d+))?\]', re.IGNORECASE),
        'CLOSE_ALL_TABS': re.compile(r'\[CLOSE[_ ]ALL[_ ]TABS?\]', re.IGNORECASE),
        'WINDOWS': re.compile(r'\[WINDOWS\]', re.IGNORECASE),
        'PROCESSES': re.compile(r'\[PROCESSES(?:\s+TOP)?\]', re.IGNORECASE),
        'KILL': re.compile(r'\[KILL\s+(.+?)\]', re.IGNORECASE),
        'SCREENSHOT': re.compile(r'\[SCREENSHOT\]', re.IGNORECASE),
        'DESKTOP': re.compile(r'\[(?:SHOW[_ ]?)?DESKTOP\]', re.IGNORECASE),
        'LOCK': re.compile(r'\[LOCK PC\]', re.IGNORECASE),
        'SHUTDOWN': re.compile(r'\[SHUTDOWN\s*(confirm)?\]', re.IGNORECASE),
        'RESTART': re.compile(r'\[RESTART\s*(confirm)?\]', re.IGNORECASE),
        'VOLUME': re.compile(r'\[VOLUME\s+(\d+)\]', re.IGNORECASE),
        'VOLUME_UP': re.compile(r'\[VOLUME UP\]', re.IGNORECASE),
        'VOLUME_DOWN': re.compile(r'\[VOLUME DOWN\]', re.IGNORECASE),
        'MUTE': re.compile(r'\[MUTE\]', re.IGNORECASE),
        'UNMUTE': re.compile(r'\[UNMUTE\]', re.IGNORECASE),
        'MONITOR_OFF': re.compile(r'\[MONITOR OFF\]', re.IGNORECASE),
        'CLIPBOARD_GET': re.compile(r'\[CLIPBOARD GET\]', re.IGNORECASE),
        'CLIPBOARD_SET': re.compile(r'\[CLIPBOARD SET\s+(.+?)\]', re.IGNORECASE),
        'CLIPBOARD_APPEND': re.compile(r'\[CLIPBOARD APPEND\s+(.+?)\]', re.IGNORECASE),
        'NOTE': re.compile(r'\[NOTE\s+(.+?)\]', re.IGNORECASE),
        'REMINDER': re.compile(r'\[REMINDER\s+(.+?)\s+через\s+(\d+)\s*(минут|минуты|минуту|мин|секунд|секунды|секунду|сек|часов|часа|час)\]', re.IGNORECASE),
        'REMINDER_LIST': re.compile(r'\[REMINDER\s+список\]', re.IGNORECASE),
        'REMINDER_DELETE': re.compile(r'\[REMINDER\s+удалить\s+(\d+)\]', re.IGNORECASE),
        'REMINDER_HISTORY': re.compile(r'\[REMINDER\s+история\]', re.IGNORECASE),
        'TIMER': re.compile(r'\[TIMER\s+(\d+)\s*(минут|минуты|минуту|мин|секунд|секунды|секунду|сек|часов|часа|час)\s+(.+?)\]', re.IGNORECASE),
        'ANIM': re.compile(r'\[ANIM:(\w+)\]', re.IGNORECASE),
        'READ_SCREEN': re.compile(r'\[READ SCREEN\]', re.IGNORECASE),
        'SCREEN_ANALYSIS': re.compile(r'\[SCREEN_ANALYSIS\s*(.*?)\]', re.IGNORECASE),
        'DISK_SPACE': re.compile(r'\[DISK_SPACE\]', re.IGNORECASE),
        'CREATE_FOLDER': re.compile(r'\[CREATE FOLDER\s+(.+?)\]', re.IGNORECASE),
        'COPY': re.compile(r'\[COPY\s+(.+?)\s+(.+?)\]', re.IGNORECASE),
        'MOVE': re.compile(r'\[MOVE\s+(.+?)\s+(.+?)\]', re.IGNORECASE),
        'DELETE': re.compile(r'\[DELETE\s+(.+?)\]', re.IGNORECASE),
        'RENAME': re.compile(r'\[RENAME\s+(.+?)\s+(.+?)\]', re.IGNORECASE),
        'EMPTY_RECYCLE': re.compile(r'\[EMPTY RECYCLE', re.IGNORECASE),
        # ===== НОВЫЕ КОМАНДЫ ДЛЯ АЛИАСОВ =====
        'REMEMBER_ALIAS': re.compile(r'\[REMEMBER_ALIAS\s+(.+?)\s+(.+?)(?:\s+as\s+(\w+))?\]', re.IGNORECASE),
        'ALIAS_LIST': re.compile(r'\[ALIAS_LIST(?:\s+(\w+))?\]', re.IGNORECASE),
        'ALIAS_DELETE': re.compile(r'\[ALIAS_DELETE\s+(.+?)\]', re.IGNORECASE),
        'REMEMBER_APP': re.compile(r'\[REMEMBER_APP\s+(.+?)\s+(.+?)\]', re.IGNORECASE),  # обратная совместимость
    }

    @staticmethod
    def parse(text: str) -> List[Dict[str, Any]]:
        """
        Парсит текст и возвращает список команд.
        Каждая команда: {'type': str, 'params': list или dict}
        """
        commands = []
        text = text or ""

        # Обработка многострочных команд (WRITE, NOTEPAD) – они удаляются из текста при парсинге
        # Сначала извлекаем WRITE
        for match in CommandParser.PATTERNS['WRITE'].finditer(text):
            path = match.group(1).strip()
            content = match.group(2).strip()
            commands.append({'type': 'WRITE', 'params': {'path': path, 'content': content}})

        # NOTEPAD
        for match in CommandParser.PATTERNS['NOTEPAD'].finditer(text):
            content = match.group(1).strip()
            commands.append({'type': 'NOTEPAD', 'params': {'content': content}})

        # TIMER (обрабатываем отдельно, т.к. у него сложная структура)
        for match in CommandParser.PATTERNS['TIMER'].finditer(text):
            amount, unit, text_rem = match.groups()
            commands.append({'type': 'TIMER', 'params': {
                'text': text_rem.strip(),
                'amount': int(amount),
                'unit': unit.strip()
            }})

        # ===== НОВЫЕ КОМАНДЫ ДЛЯ АЛИАСОВ =====
        # REMEMBER_ALIAS
        for match in CommandParser.PATTERNS['REMEMBER_ALIAS'].finditer(text):
            alias = match.group(1).strip()
            target = match.group(2).strip()
            type_ = match.group(3) if match.group(3) else ""
            commands.append({
                'type': 'REMEMBER_ALIAS',
                'params': {
                    'alias': alias,
                    'target': target,
                    'type': type_
                }
            })

        # ALIAS_LIST
        for match in CommandParser.PATTERNS['ALIAS_LIST'].finditer(text):
            type_ = match.group(1) if match.group(1) else None
            commands.append({
                'type': 'ALIAS_LIST',
                'params': {'type': type_}
            })

        # ALIAS_DELETE
        for match in CommandParser.PATTERNS['ALIAS_DELETE'].finditer(text):
            commands.append({
                'type': 'ALIAS_DELETE',
                'params': match.group(1).strip()
            })

        # REMEMBER_APP (обратная совместимость)
        for match in CommandParser.PATTERNS['REMEMBER_APP'].finditer(text):
            name = match.group(1).strip()
            path = match.group(2).strip()
            commands.append({
                'type': 'REMEMBER_APP',
                'params': {
                    'name': name,
                    'path': path
                }
            })

        # Остальные команды – однострочные
        for cmd_type, pattern in CommandParser.PATTERNS.items():
            if cmd_type in ('WRITE', 'NOTEPAD', 'TIMER', 'REMEMBER_ALIAS', 'ALIAS_LIST', 'ALIAS_DELETE', 'REMEMBER_APP'):
                continue

            if pattern is None:
                continue

            for match in pattern.finditer(text):
                if cmd_type == 'ANIM':
                    commands.append({'type': 'ANIM', 'params': match.group(1).strip().lower()})
                elif cmd_type == 'SEARCH':
                    commands.append({'type': 'SEARCH', 'params': match.group(1).strip()})
                elif cmd_type == 'LAUNCH':
                    commands.append({'type': 'LAUNCH', 'params': match.group(1).strip()})
                elif cmd_type == 'OPEN':
                    commands.append({'type': 'OPEN', 'params': match.group(1).strip()})
                elif cmd_type == 'RUN':
                    commands.append({'type': 'RUN', 'params': match.group(1).strip()})
                elif cmd_type == 'MINIMIZE':
                    commands.append({'type': 'MINIMIZE', 'params': match.group(1).strip()})
                elif cmd_type == 'MAXIMIZE':
                    commands.append({'type': 'MAXIMIZE', 'params': match.group(1).strip()})
                elif cmd_type == 'SWITCH':
                    commands.append({'type': 'SWITCH', 'params': match.group(1).strip()})
                elif cmd_type == 'CLOSE_WINDOW':
                    commands.append({'type': 'CLOSE_WINDOW', 'params': match.group(1).strip()})
                elif cmd_type == 'CLOSE_TAB':
                    count = match.group(1)
                    commands.append({'type': 'CLOSE_TAB', 'params': int(count) if count else 1})
                elif cmd_type == 'CLOSE_ALL_TABS':
                    commands.append({'type': 'CLOSE_ALL_TABS', 'params': None})
                elif cmd_type == 'WINDOWS':
                    commands.append({'type': 'WINDOWS', 'params': None})
                elif cmd_type == 'PROCESSES':
                    commands.append({'type': 'PROCESSES', 'params': None})
                elif cmd_type == 'KILL':
                    params = match.group(1).strip()
                    confirm = 'confirm' in params.lower()
                    clean = re.sub(r'confirm\s*:?', '', params, flags=re.I).strip()
                    commands.append({'type': 'KILL', 'params': {'name': clean, 'confirm': confirm}})
                elif cmd_type == 'SCREENSHOT':
                    commands.append({'type': 'SCREENSHOT', 'params': None})
                elif cmd_type == 'DESKTOP':
                    commands.append({'type': 'DESKTOP', 'params': None})
                elif cmd_type == 'LOCK':
                    commands.append({'type': 'LOCK', 'params': None})
                elif cmd_type == 'SHUTDOWN':
                    commands.append({'type': 'SHUTDOWN', 'params': {'confirm': bool(match.group(1))}})
                elif cmd_type == 'RESTART':
                    commands.append({'type': 'RESTART', 'params': {'confirm': bool(match.group(1))}})
                elif cmd_type == 'VOLUME':
                    commands.append({'type': 'VOLUME', 'params': int(match.group(1))})
                elif cmd_type == 'VOLUME_UP':
                    commands.append({'type': 'VOLUME_UP', 'params': None})
                elif cmd_type == 'VOLUME_DOWN':
                    commands.append({'type': 'VOLUME_DOWN', 'params': None})
                elif cmd_type == 'MUTE':
                    commands.append({'type': 'MUTE', 'params': None})
                elif cmd_type == 'UNMUTE':
                    commands.append({'type': 'UNMUTE', 'params': None})
                elif cmd_type == 'MONITOR_OFF':
                    commands.append({'type': 'MONITOR_OFF', 'params': None})
                elif cmd_type == 'CLIPBOARD_GET':
                    commands.append({'type': 'CLIPBOARD_GET', 'params': None})
                elif cmd_type == 'CLIPBOARD_SET':
                    commands.append({'type': 'CLIPBOARD_SET', 'params': match.group(1).strip()})
                elif cmd_type == 'CLIPBOARD_APPEND':
                    commands.append({'type': 'CLIPBOARD_APPEND', 'params': match.group(1).strip()})
                elif cmd_type == 'NOTE':
                    params = match.group(1).strip()
                    if params.lower() in ('список', 'list'):
                        commands.append({'type': 'NOTE_LIST', 'params': None})
                    elif params.lower().startswith('поиск ') or params.lower().startswith('search '):
                        q = re.sub(r'^(поиск|search)\s+', '', params, flags=re.I)
                        commands.append({'type': 'NOTE_SEARCH', 'params': q})
                    elif params.lower().startswith('clear'):
                        commands.append({'type': 'NOTE_CLEAR', 'params': {'confirm': 'confirm' in params.lower()}})
                    else:
                        commands.append({'type': 'NOTE_ADD', 'params': params})
                elif cmd_type == 'REMINDER':
                    text_rem, amount, unit = match.groups()
                    commands.append({'type': 'REMINDER', 'params': {
                        'text': text_rem.strip(),
                        'amount': int(amount),
                        'unit': unit.strip()
                    }})
                elif cmd_type == 'REMINDER_LIST':
                    commands.append({'type': 'REMINDER_LIST', 'params': None})
                elif cmd_type == 'REMINDER_DELETE':
                    commands.append({'type': 'REMINDER_DELETE', 'params': int(match.group(1))})
                elif cmd_type == 'REMINDER_HISTORY':
                    commands.append({'type': 'REMINDER_HISTORY', 'params': None})
                elif cmd_type == 'READ_SCREEN':
                    commands.append({'type': 'READ_SCREEN', 'params': None})
                elif cmd_type == 'SCREEN_ANALYSIS':
                    commands.append({'type': 'SCREEN_ANALYSIS', 'params': match.group(1).strip() or 'Что на экране?'})
                elif cmd_type == 'DISK_SPACE':
                    commands.append({'type': 'DISK_SPACE', 'params': None})
                elif cmd_type == 'CREATE_FOLDER':
                    commands.append({'type': 'CREATE_FOLDER', 'params': match.group(1).strip()})
                elif cmd_type == 'COPY':
                    commands.append({'type': 'COPY', 'params': {'src': match.group(1).strip(), 'dst': match.group(2).strip()}})
                elif cmd_type == 'MOVE':
                    commands.append({'type': 'MOVE', 'params': {'src': match.group(1).strip(), 'dst': match.group(2).strip()}})
                elif cmd_type == 'DELETE':
                    params = match.group(1).strip()
                    confirm = 'confirm' in params.lower()
                    clean = re.sub(r'confirm\s*:?', '', params, flags=re.I).strip()
                    commands.append({'type': 'DELETE', 'params': {'path': clean, 'confirm': confirm}})
                elif cmd_type == 'RENAME':
                    commands.append({'type': 'RENAME', 'params': {'old': match.group(1).strip(), 'new': match.group(2).strip()}})
                elif cmd_type == 'EMPTY_RECYCLE':
                    confirm = 'confirm' in match.group(0).lower()
                    commands.append({'type': 'EMPTY_RECYCLE', 'params': {'confirm': confirm}})

        return commands
    
    @staticmethod
    def has_commands(text: str) -> bool:
        """Проверяет, есть ли в тексте команды."""
        if not text:
            return False
        # Проверяем наличие любых команд
        for pattern in CommandParser.PATTERNS.values():
            if pattern.search(text):
                return True
        return False
    
    @staticmethod
    def strip_commands(text: str) -> str:
        """Удаляет все команды из текста, оставляя только содержание."""
        if not text:
            return ""
        
        result = text
        
        # Удаляем многострочные блоки
        for pattern in [CommandParser.PATTERNS['WRITE'], CommandParser.PATTERNS['NOTEPAD']]:
            result = pattern.sub('', result)
        
        # Удаляем однострочные команды
        for cmd_type, pattern in CommandParser.PATTERNS.items():
            if cmd_type in ('WRITE', 'NOTEPAD'):
                continue
            result = pattern.sub('', result)
        
        # Очищаем лишние пробелы
        result = re.sub(r'\n{3,}', '\n\n', result)
        result = re.sub(r'[ \t]+', ' ', result)
        result = re.sub(r'\[[A-Z_]+\]', '', result)  # Удаляем пустые скобки
        
        return result.strip()