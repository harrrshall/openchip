module TopModule (
    input        clk,
    input        reset,
    input  [7:0] in,
    output reg   done
);

    localparam DISCARD = 2'd0;
    localparam BYTE2   = 2'd1;
    localparam BYTE3   = 2'd2;

    reg [1:0] state;

    always @(posedge clk) begin
        if (reset) begin
            state <= DISCARD;
            done  <= 1'b0;
        end else begin
            case (state)
                DISCARD: begin
                    done <= 1'b0;
                    if (in[3])
                        state <= BYTE2;
                    else
                        state <= DISCARD;
                end
                BYTE2: begin
                    done  <= 1'b0;
                    state <= BYTE3;
                end
                BYTE3: begin
                    done  <= 1'b1;
                    state <= DISCARD;
                end
                default: begin
                    done  <= 1'b0;
                    state <= DISCARD;
                end
            endcase
        end
    end

endmodule
