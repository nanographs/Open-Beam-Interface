import numpy as np
import time

def ffp_8_8_to_int(num: int): #couldn't find builtin python function for this if there is one
    bits = f'{num:016b}'
    result = 0

    for n in range(8, 0, -1):
        result += pow(2,-n)*bits[n]
    for n in range(1, 9):
        result += pow(2,n)*bits[n+8]

class OBIStreamDecoder:
    raster_mode: None
    x_width: None
    y_height: None
    x_lower: None
    x_upper: None
    y_lower: None
    y_upper: None
    current_x: None
    current_y: None
    resolution_step: None

def get_new_frame_resolution_params(self, x_width, y_height):
    step = 16384/max(x_width, y_height)
    


def apply_cmd(self, cmd):
    cmd = list(cmd)
    cmd_type = cmd[0]
    if cmd_type == CmdType.RasterRegion:
        self.x_start = 256*cmd[1] + cmd[2]
        step = 256*cmd[3] + cmd[4]
        step = ffp_8_8_to_int(step)
        self.x_count = 256*cmd[5] + cmd[6]
        self.y_start = 256*cmd[7] + cmd[8]
        self.y_count = 256*cmd[9] + cmd[10]
        
def points_to_frame(self, m:memoryview, print_debug = True):
        data_length = len(m)
        if print_debug:
            print("\tdata length:", data_length)
            print("\tframe size (x, y):", self.x_width, self.y_height)
            print("\tcurrent x, current y:", self.current_x, self.current_y)
            print("\tx lower, x upper:", self.x_lower, self.x_upper)
            print("\ty lower, y upper:", self.y_lower, self.y_upper)
        
        buffer_segment_start = 0
        buffer_segment_end = 0

        while True:
            ## not bothering to deal with the case of 1 pixel by 1 pixel
            if (self.x_upper - self.x_lower) <= 1:
                break
            if (self.y_upper - self.y_lower) <= 1:
                break
            #     
            # [....................................]
            #
            #             LX    CX     UX
            #             │      │     │
            #    (0,0)    │      │     │
            #      ┌──────┼──────┼─────┼─────┐RX
            #      │      │      │     │     │
            #      │      │      │     │     │
            # LY───┼──────┼──────┼─────┼─────┤
            #      │      │      │     │     │
            #      │      │      ▼     │     │
            #  CY──┼──────┼─────►      │     │
            #      │      │            │     │
            #      │      │            │     │
            # UY───┼──────┼────────────┼─────┤
            #      │      │            │     │
            #      └──────┴────────────┴─────┘
            #     RY

            # [######..............................]
            #
            #             LX    CX     UX
            #             │      │     │
            #    (0,0)    │      │     │
            #      ┌──────┼──────┼─────┼─────┐RX
            #      │      │      │     │     │
            #      │      │      │     │     │
            # LY───┼──────┼──────┼─────┼─────┤
            #      │      │      │     │     │
            #      │      │      ▼     │     │
            #  CY──┼──────┼─────►######│     │
            #      │      │            │     │
            #      │      │            │     │
            # UY───┼──────┼────────────┼─────┤
            #      │      │            │     │
            #      └──────┴────────────┴─────┘
            #     RY
            #
            

            ### ===========================STEP A: FIRST LINE================================
            if not self.current_x == self.x_lower:
                if print_debug:
                    print("\t===STEP 1: FIRST LINE===")
                buffer_segment_end += self.x_upper - self.current_x
                if buffer_segment_end > data_length: ## if the data doesn't reach the end of the line
                    self.buffer[self.current_y][self.current_x:(self.current_x+data_length)] =\
                        m[buffer_segment_start:data_length].cast('B')
                    break
                

                if print_debug:
                    print(f'\t\t packet [{buffer_segment_start}:{buffer_segment_end}] out of {data_length}')
                    print(f'\t\t      {self.x_lower: <5}    {self.current_x: <5}           {self.x_upper: <5}')
                    print(f'\t\t{self.current_y: <5} [--------#################]     ')

                self.buffer[self.current_y][self.current_x:self.x_upper] =\
                    m[buffer_segment_start:buffer_segment_end].cast('B')
                buffer_segment_start += buffer_segment_end
                
                self.current_x = self.x_lower


                self.current_y += 1
                ### roll over into the next frame if necessary
                if self.current_y == self.y_upper:
                    if print_debug:
                        print(f'\tat end of frame, y = {self.current_y} --> y = {self.y_upper}')
                    self.current_y = self.y_lower
            

            ### ===========================STEP 2: FULL LINES TO END OF FRAME================================
            full_lines = (data_length - buffer_segment_start)//(self.x_upper - self.x_lower)
            total_full_lines = full_lines
            if print_debug:
                print("\t===STEP 2: FULL LINES TO END OF FRAME===")
                print(f'\t\tpacket contains {full_lines} full lines')

            while (self.current_y + full_lines) >= self.y_upper:
                #  [######..............................]
                #        ^
                #
                #       LX         UX
                #       |          |
                #   CY──............ 
                #       ............
                #       ............
                #   UY──............──lines_left_in_frame
                #       ............──full_lines
                #       .....  
                #   

                lines_left_in_frame = self.y_upper - self.current_y

                
                #             LX           UX
                #             CX           │
                #    (0,0)    │            │
                #      ┌──────┼────────────┼─────┐RX
                #      │      │            │     │
                #      │      │            │     │
                # LY───┼──────┼────────────┼─────┤
                #      │      │            │     │
                #      │      |            │     │
                #      │      ▼      ######│     │
                #  CY──┼──────►++++++++++++│     │
                #      │      │++++++++++++│     │
                # UY───┼──────┼────────────┼─────┤
                #      │      │            │     │
                #      └──────┴────────────┴─────┘
                #     RY
                #
                # [######++++++++++++++++++++++++......]  

                buffer_segment_end += (self.x_upper - self.x_lower)*lines_left_in_frame

                if print_debug:
                    print(f'\t\t packet [{buffer_segment_start}:{buffer_segment_end}] out of {data_length}')
                    print(f'\t\t with shape ({lines_left_in_frame},{self.x_upper-self.x_lower})')
                    print(f'\t\t      {self.x_lower: <5}                    {self.x_upper: <5}')
                    print(f'\t\t{self.current_y: <5} [+++++++++++++++++++++++++]     ')
                    print(f'\t\t      [+++++++++++++++++++++++++]     +{lines_left_in_frame} lines')
                    print(f'\t\t{self.y_upper: <5}                    {full_lines - lines_left_in_frame} remaining / {total_full_lines} total')
                    
                self.buffer[self.current_y:self.y_upper,self.x_lower:self.x_upper] = \
                    m[buffer_segment_start:buffer_segment_end]\
                        .cast('B',shape = (lines_left_in_frame, (self.x_upper - self.x_lower)))
                
                buffer_segment_start = buffer_segment_end
                full_lines -= lines_left_in_frame
                self.current_y = self.y_lower

            #if self.current_y + full_lines < self.y_upper: 
            if full_lines > 0:
                if print_debug:
                    print(f'\t===STEP 2B: FULL LINES, SAME FRAME ===')
                #  [######..............................]
                #        ^
                #
                #       LX         UX
                #       |          |
                #   CY__............ 
                #       ............__ full_lines
                #       ......
                #   UY__   
                #     

                #
                #             LX           UX
                #             CX           │
                #    (0,0)    │            │
                #      ┌──────┼────────────┼─────┐RX
                #      │      │            │     │
                #      │      │            │     │
                # LY───┼──────┼────────────┼─────┤
                #      │      │            │     │
                #      │      |            │     │
                #      │      ▼      ######│     │
                #  CY──┼──────►++++++++++++│     │
                #      │      │++++++++++++│     │
                # UY───┼──────┼────────────┼─────┤
                #      │      │            │     │
                #      └──────┴────────────┴─────┘
                #     RY
                #
                # [######++++++++++++++++++++++++......]

                buffer_segment_end += (self.x_upper - self.x_lower)*full_lines
                
                if print_debug:
                    print(f'\t\t packet [{buffer_segment_start}:{buffer_segment_end}] out of {data_length}')
                    print(f'\t\t with shape ({full_lines},{self.x_upper-self.x_lower})')
                    print(f'\t\t      {self.x_lower: <5}                    {self.x_upper: <5}')
                    print(f'\t\t{self.current_y: <5} [+++++++++++++++++++++++++]     ')
                    print(f'\t\t      [+++++++++++++++++++++++++]     +{full_lines} lines')
                    print(f'\t\t{self.current_y+full_lines: <5}                    0 remaining / {total_full_lines} total')
                self.buffer[self.current_y:self.current_y + full_lines, self.x_lower:self.x_upper] = \
                    m[buffer_segment_start:buffer_segment_end]\
                        .cast('B', shape = (full_lines, self.x_upper - self.x_lower))
                
                buffer_segment_start = buffer_segment_end
                self.current_y += full_lines


            #             LX    CX     UX
            #             |     |      │
            #    (0,0)    │     |      │
            #      ┌──────┼─────┼──────┼─────┐RX
            #      │      │     |      │     │
            #      │      │     |      │     │
            # LY───┼──────┼─────┼──────┼─────┤
            #      │      │     |      │     │
            #      │      |     |      │     │
            #      │      |     |######│     │
            #      |      |+++++|++++++│     │
            #      │      │+++++▼++++++│     │
            # CY───┼──────►@@@@@@      │     │
            # UY───┼──────┼────────────┼─────┤
            #      │      │            │     │
            #      └──────┴────────────┴─────┘
            #     RY
            #
            # [######++++++++++++++++++++++++@@@@@@]  
            #                               ^     ^ 

            ### ===========================STEP 3: LAST LINE================================
            remaining_points = data_length - buffer_segment_start
            self.current_x = self.x_lower + remaining_points


            


            if remaining_points > 0:
                if print_debug:
                    print("\t===STEP 3: LAST LINE===")
                    print(f'\t\t{remaining_points} remaining, brings current x to {self.current_x}')
                    print(f'\t\t packet [{buffer_segment_start}:{data_length}] out of {data_length}')
                    print(f'\t\t      {self.x_lower: <5}    {self.current_x: <5}           {self.x_upper: <5}')
                    print(f'\t\t{self.current_y: <5} [@@@@@@@@-----------------]     ')

                self.buffer[self.current_y, self.x_lower:self.current_x] = \
                    m[buffer_segment_start:data_length].cast('B')

            
            break



