#!/usr/bin/env python3

import numpy as np
import trimesh
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import logging

# ===================== НАСТРОЙКИ =====================

BED_SIZE_X = 300
BED_SIZE_Y = 300

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SmartBed")

# ===================== ГЕОМЕТРИЯ =====================

def compute_zones(min_x, min_y, max_x, max_y):
    zones = [False] * 9

    zone_w = BED_SIZE_X / 3
    zone_h = BED_SIZE_Y / 3

    for i in range(3):
        for j in range(3):
            idx = i * 3 + j

            zx_min = j * zone_w
            zx_max = (j + 1) * zone_w
            zy_min = i * zone_h
            zy_max = (i + 1) * zone_h

            intersect = not (
                zx_max < min_x or zx_min > max_x or
                zy_max < min_y or zy_min > max_y
            )

            zones[idx] = intersect

    return zones

# ===================== ВИЗУАЛИЗАЦИЯ =====================

def visualize(zones, min_x, min_y, max_x, max_y):
    fig, ax = plt.subplots()

    def update(frame):
        ax.clear()

        # Рисуем зоны
        for i in range(3):
            for j in range(3):
                idx = i * 3 + j
                color = "red" if zones[idx] else "blue"

                rect = plt.Rectangle((j, i), 1, 1, color=color, alpha=0.5)
                ax.add_patch(rect)

        # Рисуем модель (bbox)
        model_rect = plt.Rectangle(
            (min_x / (BED_SIZE_X / 3), min_y / (BED_SIZE_Y / 3)),
            (max_x - min_x) / (BED_SIZE_X / 3),
            (max_y - min_y) / (BED_SIZE_Y / 3),
            fill=False,
            edgecolor='black',
            linewidth=2
        )
        ax.add_patch(model_rect)

        ax.set_xlim(0, 3)
        ax.set_ylim(0, 3)
        ax.set_title("Красный = активные зоны | Чёрный = модель")
        ax.set_aspect('equal')

    anim = animation.FuncAnimation(fig, update, frames=10, interval=500)
    plt.show()

# ===================== ОСНОВНАЯ ЛОГИКА =====================

def process_stl(stl_path):
    logger.info(f"Загрузка STL: {stl_path}")

    mesh = trimesh.load(stl_path)

    # bounds
    min_x, min_y, _ = mesh.bounds[0]
    max_x, max_y, _ = mesh.bounds[1]

    # смещение в (0,0)
    mesh.apply_translation([-min_x, -min_y, 0])

    min_x, min_y, _ = mesh.bounds[0]
    max_x, max_y, _ = mesh.bounds[1]

    logger.info(f"Размер модели: {max_x:.1f} x {max_y:.1f} мм")

    zones = compute_zones(min_x, min_y, max_x, max_y)

    # вывод в консоль
    print("\nАктивные зоны:")
    for i in range(3):
        row = zones[i*3:(i+1)*3]
        print(row)

    visualize(zones, min_x, min_y, max_x, max_y)

# ===================== ЗАПУСК =====================

if __name__ == "__main__":
    stl_path = r"C:\Users\belos\Desktop\model.stl"  # ← твой файл
    process_stl(stl_path)