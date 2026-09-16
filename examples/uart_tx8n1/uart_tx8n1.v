module uart_tx8n1 #(parameter CLKS_PER_BIT = 4) (
    input  wire       clk,
    input  wire       reset,
    input  wire       start,
    input  wire [7:0] data,
    output reg        tx,
    output reg        busy,
    output reg        done
);

    reg [7:0] data_reg;
    integer   cnt;      // cycle counter within a bit period: 0 .. CLKS_PER_BIT-1
    integer   bitidx;   // bit index: 0=start, 1..8=data[0..7], 9=stop

    always @(posedge clk) begin
        if (reset) begin
            // Synchronous active-high reset with priority: discard any frame.
            tx     <= 1'b1;
            busy   <= 1'b0;
            done   <= 1'b0;
            cnt    <= 0;
            bitidx <= 0;
        end else if (!busy) begin
            // Idle state: line high, no done pulse unless just completed
            // (completion is handled in the busy branch below).
            done <= 1'b0;
            if (start) begin
                // Accept a new frame at edge k: latch data, drive start bit.
                data_reg <= data;
                tx       <= 1'b0;   // start bit
                busy     <= 1'b1;
                cnt      <= 0;
                bitidx   <= 0;
            end else begin
                tx <= 1'b1;
            end
        end else begin
            // Busy: transmitting a frame.
            // done is reassigned every cycle; it is high only for the cycle
            // beginning at edge k+10*CLKS_PER_BIT (the completion edge).
            done <= (bitidx == 9) && (cnt == CLKS_PER_BIT - 1);

            if (cnt == CLKS_PER_BIT - 1) begin
                // Last cycle of the current bit period: advance.
                cnt <= 0;
                if (bitidx == 9) begin
                    // Stop bit finished: return to idle at edge k+10*CLKS_PER_BIT.
                    bitidx <= 0;
                    busy   <= 1'b0;
                    tx     <= 1'b1;
                end else begin
                    bitidx <= bitidx + 1;
                    if (bitidx == 8)
                        tx <= 1'b1;                  // enter stop bit
                    else
                        tx <= data_reg[bitidx];      // enter data bit (LSB first)
                end
            end else begin
                cnt <= cnt + 1;
                // tx holds its current bit value for the rest of the period.
            end
        end
    end

endmodule
