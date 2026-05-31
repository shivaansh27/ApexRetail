# Polygon ROIs (Regions of Interest) mapping camera screen coordinates to physical brand zones.
# Each polygon is defined by list of tuples: [(x1, y1), (x2, y2), ...]

# Brigade Road Store Camera Mappings:
# CAM 1: Entry / Exit threshold
# CAM 2: Top Wall product zones (EB Korean, Face Shop, Good Vibes, DermDoc, Minimalist, Aqualogica, Lakme Skin)
# CAM 3: Bottom Wall product zones (Maybelline, Faces Canada, Lakme, Colorbar + Sugar, Swiss Beauty, Renee / NY Bae)
# CAM 4: Center Floor Makeup Units & Gondolas (Makeup Unit, Alps Goodness, Streax)
# CAM 5: Cash Counter queue & PMU area (Cash Counter queue join threshold, PMU counter)

CAM_ROIS = {
    "CAM_1": {
        "ENTRY_ZONE": [(100, 300), (300, 300), (300, 450), (100, 450)],
        "EXIT_ZONE": [(100, 150), (300, 150), (300, 300), (100, 300)],
    },
    "CAM_2": {
        "EB_KOREAN": [(50, 50), (150, 50), (150, 150), (50, 150)],
        "THE_FACE_SHOP": [(160, 50), (280, 50), (280, 150), (160, 150)],
        "GOOD_VIBES": [(290, 50), (390, 50), (390, 150), (290, 150)],
        "DERMDOC": [(400, 50), (500, 50), (500, 150), (400, 150)],
        "MINIMALIST": [(510, 50), (610, 50), (610, 150), (510, 150)],
        "AQUALOGICA": [(620, 50), (720, 50), (720, 150), (620, 150)],
        "LAKME_SKIN": [(730, 50), (830, 50), (830, 150), (730, 150)]
    },
    "CAM_3": {
        "MAYBELLINE": [(50, 350), (150, 350), (150, 450), (50, 450)],
        "FACES_CANADA": [(160, 350), (280, 350), (280, 450), (160, 450)],
        "LAKME": [(290, 350), (390, 350), (390, 450), (290, 450)],
        "COLORBAR_SUGAR": [(400, 350), (500, 350), (500, 450), (400, 450)],
        "SWISS_BEAUTY": [(510, 350), (610, 350), (610, 450), (510, 450)],
        "RENEE_NYBAE": [(620, 350), (720, 350), (720, 450), (620, 450)]
    },
    "CAM_4": {
        "MAKEUP_UNIT": [(350, 180), (550, 180), (550, 300), (350, 300)],
        "ALPS_GOODNESS": [(630, 350), (730, 350), (730, 450), (630, 450)],
        "STREAX": [(740, 350), (840, 350), (840, 450), (740, 450)]
    },
    "CAM_5": {
        "BILLING_QUEUE": [(600, 150), (800, 150), (800, 400), (600, 400)],
        "PMU": [(780, 300), (880, 300), (880, 420), (780, 420)]
    }
}

def is_point_in_polygon(x, y, polygon):
    """
    Ray-casting algorithm to determine if a point (x, y) is inside a polygon [(x1, y1), ...]
    """
    num_vertices = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(1, num_vertices + 1):
        p2x, p2y = polygon[i % num_vertices]
        if y > min(p1y, p2y) and y <= max(p1y, p2y):
            if x <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                else:
                    xinters = p1x
                if p1x == p2x or x <= xinters:
                    inside = not inside
        p1x, p1y = p2x, p2y
    return inside
