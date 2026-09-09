module updown_counter_props(
  input clk, input rst, input en, input up, input load, input [7:0] load_val, input [7:0] count
);
  reg past_valid = 1'b0;
  reg [7:0] prev; reg prev_load, prev_en, prev_up; reg [7:0] prev_lv;
  always @(posedge clk) begin
    prev <= count; prev_load <= load; prev_en <= en; prev_up <= up; prev_lv <= load_val;
    past_valid <= !rst;
    if (rst) begin
      // nothing
    end else if (past_valid) begin
      if (prev_load) assert(count == prev_lv);
      else if (prev_en && prev_up) assert(count == prev + 8'd1);
      else if (prev_en) assert(count == prev - 8'd1);
      else assert(count == prev);
    end
    cover(past_valid && count == 8'd0 && prev == 8'd255);
  end
endmodule
