#!/bin/bash

mkdir -p Merged

# Перебираем все .mkv файлы
for video in *.mkv; do
    echo "Видео: $video"

    # Извлекаем номер эпизода (ep.XX)
    if [[ "$video" =~ ep\.([0-9]{2}) ]]; then
        ep_number="${BASH_REMATCH[1]}"
        echo "Эпизод: $ep_number"

        # Ищем .mka файл с тем же номером эпизода
        audio_file=$(ls *"ep.${ep_number}"*.mka 2>/dev/null | head -n 1)

        if [[ -n "$audio_file" ]]; then
            echo "Аудио: $audio_file"
            output_file="Merged/${video}"
            ffmpeg -i "$video" -i "$audio_file" -map 0:v -map 1:a -c:v copy -c:a copy "$output_file"
        else
            echo "Аудио для ep.${ep_number} не найдено!"
        fi
    else
        echo "Не удалось определить номер эпизода в имени файла: $video"
    fi

    echo "----"
done
