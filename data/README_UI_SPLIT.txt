Разделение GUI Лисички
======================

Что это
-------
gui.py разрезан на пакет ui/. Поведение окна то же:
чат, аватар, голос, вложения, стрим, [ANIM:], настройки.

main.py менять не нужно:
    from gui import AssistantWindow

Куда класть
-----------
Скопировать поверх D:\asistent\data\ :

    data/gui.py          ← тонкий шим
    data/ui/             ← новый пакет
        __init__.py
        window.py
        composer.py
        status_bar.py
        avatar_ctrl.py
        attachments.py
        theme.py

Не удалять уже существующие:
    chat_panel.py
    gui_voice.py
    avatar_window.py
    settings_dialog.py
    splash.py

Схема
-----
    main.py
      → gui.AssistantWindow          (шим)
          → ui.window.AssistantWindow
              chat_panel.ChatPanel   (как было)
              ui.composer            поле + кнопки
              ui.status_bar          ● готово / думаю
              ui.avatar_ctrl         только применяет [ANIM:]
              ui.attachments         файл / превью
              gui_voice.VoiceInputMixin

GUI по-прежнему вызывает assistant.generate_stream — это следующий
шаг (вынести в отдельный поток), не этот архив.

Откат
-----
Вернуть старый gui.py из gui.py.bak и удалить папку ui/.
