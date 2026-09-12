`timescale 1ns/1ps
module tb;
  reg clk=0, rst=0, clear=0, enable=0, event_i=0;
  wire [7:0] count;
  event_counter dut(.clk(clk), .rst(rst), .clear(clear), .enable(enable),
                    .event_i(event_i), .count(count));
  integer expected=0, previous=0, cases=0;
  integer sequence_id, bit_id, i;
  reg [31:0] random_state=32'h41b5269a;
  task step;
    input r, c, en, ev;
    begin
      clk=0; rst=r; clear=c; enable=en; event_i=ev;
      #2;
      if (cases > 0 && count !== expected[7:0]) begin
        $display("FAIL before edge case=%0d got=%0d expected=%0d", cases,count,expected);
        $fatal(1);
      end
      if (r) begin expected=0; previous=0; end
      else begin
        if (c) expected=0;
        else if (en && ev && !previous && expected<255) expected=expected+1;
        previous=ev;
      end
      clk=1; #2;
      if (count !== expected[7:0]) begin
        $display("FAIL after edge case=%0d got=%0d expected=%0d", cases,count,expected);
        $fatal(1);
      end
      cases=cases+1;
    end
  endtask
  initial begin
    step(1,0,0,0);
    // Disabled events must be consumed; clear must not erase history.
    step(0,0,0,1); step(0,0,1,1); step(0,0,1,0); step(0,0,1,1);
    step(0,1,1,1); step(0,0,1,1); step(0,0,1,0); step(0,0,1,1);
    // Reset and clear both win over a simultaneous new event.
    step(0,0,1,0); step(0,1,1,1); step(1,1,1,1); step(0,0,1,1);
    // Every 12-sample binary event history with counting enabled.
    for (sequence_id=0; sequence_id<4096; sequence_id=sequence_id+1) begin
      step(1,0,0,0);
      for (bit_id=0; bit_id<12; bit_id=bit_id+1)
        step(0,0,1,(sequence_id >> bit_id)&1);
    end
    // Reach saturation and keep exercising event and hold paths beyond it.
    step(1,0,0,0);
    for (i=0; i<300; i=i+1) begin step(0,0,1,0); step(0,0,1,1); end
    step(0,0,0,0); step(0,0,0,1); step(0,1,1,1); step(0,0,1,1);
    // Deterministic independent mixed controls, including reset/clear priority.
    for (i=0; i<10000; i=i+1) begin
      random_state=random_state ^ (random_state << 13);
      random_state=random_state ^ (random_state >> 17);
      random_state=random_state ^ (random_state << 5);
      step((random_state[7:0]==0), (random_state[11:8]==0),
           random_state[12], random_state[13]);
    end
    $display("PASS cases=%0d exhaustive_event_histories=4096",cases);
    $finish;
  end
endmodule
