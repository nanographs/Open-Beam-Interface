def filled_box(x_start, y_start, x_width, y_height, dwell):
    ## start ______ x = x_start + x_width, y = y_start
    ##       |    |
    ##       ------ x = x_start + x_width, y = y_start + y_height
    for y in range(y_start, y_start+y_height):
        for x in range(x_start, x_start+x_width):
            seq.add(BlankCommand(enable=False, inline=True))
            seq.add(VectorPixelCommand(x_coord=x, y_coord = y, dwell = dwell))
            seq.add(BlankCommand(enable=True))

def array_of_squares(square_width: int, square_spacing: int, squares_per_side: int,
    dwells:list):
    x = 0
    y = 0
    for square_y in range(squares_per_side):
        for square_x in range(squares_per_side):
            filled_box(x, y, x+square_width, y+square_width, dwells[square_x * square_y])
            x += square_spacing
        y += square_spacing

def line(x_start, x_count, x_step, y, dwell):
    for x in range(x_start, x_start+(x_count*x_step), x_step):
        seq.add(BlankCommand(enable=False, inline=True))
        seq.add(VectorPixelCommand(x_coord=x, y_coord = y, dwell = dwell))
        seq.add(BlankCommand(enable=True))
