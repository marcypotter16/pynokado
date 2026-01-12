def point_dist_rect(point, rect):
    """
    Returns the distance between a point and a rectangle
    :param point: The point
    :param rect: The rectangle
    :return: The distance
    """
    return max(abs(point[0] - rect.x), abs(point[0] - rect.x - rect.w), abs(point[1] - rect.y), abs(point[1] - rect.y - rect.h))