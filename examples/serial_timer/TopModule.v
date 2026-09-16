module TopModule (
    input  clk,
    input  reset,
    input  data,
    output [3:0] count,
    output counting,
    output done,
    input  ack
);

    localparam SEARCH = 2'd0;
    localparam SHIFT  = 2'd1;
    localparam COUNT  = 2'd2;
    localparam DONE   = 2'd3;

    reg [1:0]  state;
    reg [1:0]  next_state;
    reg [3:0]  sr;
    reg [3:0]  delay;
    reg [1:0]  shift_cnt;
    reg [13:0] cnt;
    reg [9:0]  sub;      // modulo-1000 phase counter

    reg [3:0]  count_r;
    reg        counting_r;
    reg        done_r;

    assign count    = count_r;
    assign counting = counting_r;
    assign done     = done_r;

    // Next-state logic
    always @* begin
        case (state)
            SEARCH: next_state = ({sr[2:0], data} == 4'b1101) ? SHIFT : SEARCH;
            SHIFT:  next_state = (shift_cnt == 2'd3) ? COUNT : SHIFT;
            COUNT:  next_state = (cnt == (({1'b0, delay} + 14'd1) * 14'd1000) - 14'd1) ? DONE : COUNT;
            DONE:   next_state = (ack) ? SEARCH : DONE;
            default: next_state = SEARCH;
        endcase
    end

    // State, datapath, and registered outputs
    always @(posedge clk) begin
        if (reset) begin
            state      <= SEARCH;
            sr         <= 4'b0000;
            delay      <= 4'b0000;
            shift_cnt  <= 2'd0;
            cnt        <= 14'd0;
            sub        <= 10'd0;
            count_r    <= 4'b0000;
            counting_r <= 1'b0;
            done_r     <= 1'b0;
        end else begin
            counting_r <= (next_state == COUNT);
            done_r     <= (next_state == DONE);
            case (state)
                SEARCH: begin
                    sr      <= {sr[2:0], data};
                    count_r <= 4'b0000;
                    if (next_state == SHIFT)
                        shift_cnt <= 2'd0;
                end
                SHIFT: begin
                    delay     <= {delay[2:0], data};
                    shift_cnt <= shift_cnt + 2'd1;
                    if (next_state == COUNT) begin
                        cnt     <= 14'd0;
                        sub     <= 10'd0;
                        count_r <= {delay[2:0], data}; // delay captured on this edge
                    end else begin
                        count_r <= 4'b0000;
                    end
                end
                COUNT: begin
                    cnt <= cnt + 14'd1;
                    if (next_state == COUNT) begin
                        if (sub == 10'd999)
                            count_r <= count_r - 4'd1;
                        sub <= (sub == 10'd999) ? 10'd0 : sub + 10'd1;
                    end else begin
                        count_r <= 4'b0000;
                    end
                end
                DONE: begin
                    count_r <= 4'b0000;
                    if (next_state == SEARCH)
                        sr <= 4'b0000;
                end
                default: state <= SEARCH;
            endcase
            state <= next_state;
        end
    end

endmodule
