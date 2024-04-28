import math
import numpy as np

def circle(r):
    for degree in range(360):
        x = r*math.cos(math.radians(degree))
        y = r*math.sin(math.radians(degree))
    yield x, y

def rose(a, b, n_points):
    theta = np.linspace(0, 2*np.pi, n_points)
    r = a*np.sin(b*theta)
    return r, theta
    
def spiral(n_points, n_loops):
    theta = np.linspace(0, 2*n_loops*np.pi, n_points)
    r = theta
    return r, theta

def polar_to_cartesian(f):
    r, theta = f
    x = r*np.cos(theta)
    y = r*np.sin(theta)
    return x, y

def scale_to_dac_range(f):
    x, y = f
    max_x, min_x, max_y, min_y = np.max(x), np.min(x), np.max(y), np.min(y)
    max_range = max(max_x - min_x, max_y - min_y)
    scale_factor = 16384/max_range
    x = (x - min_x)*scale_factor #shift and scale
    y = (y - min_y)*scale_factor
    x = x.astype("int")
    y = y.astype("int")
    return zip(x, y)

r = scale_to_dac_range(polar_to_cartesian(rose(2, 5, 100)))
for x, y in r:
    print(f"{x=}, {y=}")
