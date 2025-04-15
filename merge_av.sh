#!/bin/bash

mkdir -p Merged

for video in *.mkv; do
    echo "Видео: $video"

    ep_number=""

    # Пытаемся найти номер эпизода: сначала в формате [01], затем ep.01
    if [[ "$video" =~ \[([0-9]{1,2})\] ]]; then
        ep_number="${BASH_REMATCH[1]}"
    elif [[ "$video" =~ ep\.([0-9]{1,2}) ]]; then
        ep_number="${BASH_REMATCH[1]}"
    fi

    # Если нашли — нормализуем до двух цифр (например, 1 → 01)
    if [[ -n "$ep_number" ]]; then
        ep_number=$(printf "%02d" "$ep_number")
        echo "Номер эпизода: $ep_number"

        # Ищем .mka файл с тем же номером в любом формате
        audio_file=$(ls *"ep.${ep_number}"*.mka *"[${ep_number}]"*.mka 2>/dev/null | head -n 1)

        if [[ -n "$audio_file" ]]; then
            echo "Аудио: $audio_file"
            output_file="Merged/${video}"
            ffmpeg -i "$video" -i "$audio_file" -map 0:v -map 1:a -c:v copy -c:a copy "$output_file"
        else
            echo "Аудио для эпизода $ep_number не найдено!"
        fi
    else
        echo "Не удалось определить номер эпизода в имени файла: $video"
    fi

    echo "----"
done
