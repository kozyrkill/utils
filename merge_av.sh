#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

mkdir -p Merged

echo -e "${YELLOW}Анализируем .mkv файлы и извлекаем числовые последовательности...${NC}"

declare -A video_to_numbers
declare -A number_to_video

for video in *.mkv; do
    nums=($(grep -oE '[0-9]{1,4}' <<< "$video"))
    video_to_numbers["$video"]="${nums[*]}"
done

declare -A freq
for num_list in "${video_to_numbers[@]}"; do
    for n in $num_list; do
        freq["$n"]=$((freq["$n"] + 1))
    done
done

candidates=()
for n in "${!freq[@]}"; do
    if [[ ${freq[$n]} -eq 1 ]]; then
        candidates+=("$n")
    fi
done

IFS=$'\n' sorted_candidates=($(sort -n <<<"${candidates[*]}"))
unset IFS

declare -A episode_map

for ep in "${sorted_candidates[@]}"; do
    for video in "${!video_to_numbers[@]}"; do
        for num in ${video_to_numbers["$video"]}; do
            if [[ "$num" == "$ep" ]]; then
                if [[ -z "${episode_map[$ep]}" ]]; then
                    episode_map[$ep]="$video"
                fi
            fi
        done
    done
done

if [[ ${#episode_map[@]} -ne $(ls *.mkv | wc -l) ]]; then
    echo -e "${RED}❌ Несоответствие: найдено ${#episode_map[@]} эпизодов, но $(ls *.mkv | wc -l) видеофайлов.${NC}"
    exit 1
fi

# Поиск подпапок с mka
echo -e "${YELLOW}Поиск папок с .mka файлами...${NC}"
mapfile -t audio_dirs < <(find . -type f -iname "*.mka" -printf "%h\n" | sort -u)

if [[ ${#audio_dirs[@]} -eq 0 ]]; then
    echo -e "${RED}❌ Ошибка: .mka файлы не найдены!${NC}"
    exit 1
elif [[ ${#audio_dirs[@]} -eq 1 ]]; then
    selected_dir="${audio_dirs[0]}"
    echo -e "${GREEN}Найдена одна папка: $selected_dir${NC}"
else
    echo "Найдено несколько папок:"
    for i in "${!audio_dirs[@]}"; do
        echo "$((i+1))) ${audio_dirs[i]}"
    done
    read -p "Выберите номер: " choice
    selected_dir="${audio_dirs[$((choice-1))]}"
    echo -e "${GREEN}Выбрана папка: $selected_dir${NC}"
fi

# Проверка наличия аудио по отсортированному порядку
missing_audio=()
for ep in $(printf "%s\n" "${!episode_map[@]}" | sort -n); do
    if [[ "$ep" =~ ^[0-9]+$ ]]; then
        ep_number=$(printf "%02d" "$((10#$ep))")
    else
        echo -e "${YELLOW}⚠ Пропущен некорректный номер эпизода: '$ep'${NC}"
        continue
    fi

    audio_file=$(find "$selected_dir" -type f -iname "*${ep_number}*.mka" | head -n 1)
    if [[ -z "$audio_file" ]]; then
        missing_audio+=("$ep_number")
    fi
done

if [[ ${#missing_audio[@]} -gt 0 ]]; then
    echo -e "${RED}❌ Отсутствуют аудиофайлы для эпизодов:${NC}"
    printf '  - %s\n' "${missing_audio[@]}"
    exit 1
fi

echo -e "${GREEN}✓ Все проверки пройдены. Начинаю объединение по порядку...${NC}"

# Обработка по порядку
for ep in $(printf "%s\n" "${!episode_map[@]}" | sort -n); do
    if [[ "$ep" =~ ^[0-9]+$ ]]; then
        ep_number=$(printf "%02d" "$((10#$ep))")
    else
        echo -e "${YELLOW}⚠ Пропущен некорректный номер эпизода: '$ep'${NC}"
        continue
    fi

    video="${episode_map[$ep]}"
    audio_file=$(find "$selected_dir" -type f -iname "*${ep_number}*.mka" | head -n 1)

    echo -e "${YELLOW}🎞️ Эпизод $ep_number: $video + $audio_file${NC}"
    output_file="Merged/${video}"
    ffmpeg -i "$video" -i "$audio_file" -map 0:v -map 1:a -c:v copy -c:a copy "$output_file"
    echo -e "${GREEN}✓ Готово: $output_file${NC}"
    echo "----"
done
