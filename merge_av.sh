#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

mkdir -p Merged

echo -e "${YELLOW}Определение эпизодов по имени .mkv...${NC}"

declare -A episode_map

for video in *.mkv; do
    if [[ "$video" =~ -[[:space:]]([0-9]{1,3})[[:space:]] ]]; then
        ep_number=$(printf "%02d" "$((10#${BASH_REMATCH[1]}))")
        episode_map["$ep_number"]="$video"
    else
        echo -e "${RED}❌ Не удалось определить номер эпизода: $video${NC}"
        exit 1
    fi
done

# Поиск папки с .mka
echo -e "${YELLOW}Поиск папок с .mka...${NC}"
mapfile -t audio_dirs < <(find . -type f -iname "*.mka" -printf "%h\n" | sort -u)

if [[ ${#audio_dirs[@]} -eq 0 ]]; then
    echo -e "${RED}❌ .mka файлы не найдены!${NC}"
    exit 1
elif [[ ${#audio_dirs[@]} -eq 1 ]]; then
    selected_dir="${audio_dirs[0]}"
    echo -e "${GREEN}Найдена папка: $selected_dir${NC}"
else
    echo "Найдено несколько папок с .mka:"
    for i in "${!audio_dirs[@]}"; do
        echo "$((i+1))) ${audio_dirs[i]}"
    done
    read -p "Выберите номер: " choice
    selected_dir="${audio_dirs[$((choice-1))]}"
    echo -e "${GREEN}Выбрана папка: $selected_dir${NC}"
fi

# Проверка аудиофайлов
missing_audio=()
for ep in $(printf "%s\n" "${!episode_map[@]}" | sort -n); do
    # Жёсткий поиск — ищем mka, где в имени есть ` - XX `
    audio_file=$(find "$selected_dir" -type f -iname "* - ${ep} *.mka" | head -n 1)
    if [[ -z "$audio_file" ]]; then
        audio_file=$(find "$selected_dir" -type f -iname "*${ep}*.mka" | head -n 1)
        if [[ -z "$audio_file" ]]; then
            missing_audio+=("$ep")
        fi
    fi
done

if [[ ${#missing_audio[@]} -gt 0 ]]; then
    echo -e "${RED}❌ Отсутствуют .mka файлы для эпизодов:${NC}"
    printf '  - %s\n' "${missing_audio[@]}"
    exit 1
fi

# Объединение
echo -e "${GREEN}✓ Всё готово. Начинаю объединение...${NC}"

for ep in $(printf "%s\n" "${!episode_map[@]}" | sort -n); do
    video="${episode_map[$ep]}"
    audio_file=$(find "$selected_dir" -type f -iname "* - ${ep} *.mka" | head -n 1)
    [[ -z "$audio_file" ]] && audio_file=$(find "$selected_dir" -type f -iname "*${ep}*.mka" | head -n 1)

    echo -e "${YELLOW}🎞️ Эпизод $ep: $video + $audio_file${NC}"
    output_file="Merged/${video}"
    ffmpeg -i "$video" -i "$audio_file" -map 0:v -map 1:a -c:v copy -c:a copy "$output_file"
    echo -e "${GREEN}✓ Готово: $output_file${NC}"
    echo "----"
done
