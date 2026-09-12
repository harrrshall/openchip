// Independent development oracle from registered_sum_request.md.
// Never supplied to the runtime model. This is not a held-out suite asset.
`timescale 1ns/1ps
module tb;
  reg clk=0, rst=0, en=0;
  reg [7:0] a=0, b=0;
  wire [7:0] q;
  registered_sum dut(.clk(clk), .rst(rst), .en(en), .a(a), .b(b), .q(q));
  integer expected=0, cases=0, x, y, i, wide_sum;
  task tick;
    input reset_value, enable_value;
    input [7:0] input_a, input_b;
    integer previous;
    begin
      previous=expected;
      clk=0; rst=reset_value; en=enable_value; a=input_a; b=input_b;
      if (reset_value) expected=0;
      else if (enable_value) begin
        wide_sum = {1'b0,input_a} + {1'b0,input_b};
        expected = wide_sum > 255 ? 255 : wide_sum;
      end
      #1;
      if (cases > 0 && q !== previous[7:0]) begin
        $display("FAIL output changed before clock edge case=%0d",cases+1);
        $fatal(1);
      end
      #4; clk=1; #1;
      cases=cases+1;
      if (q !== expected[7:0]) begin
        $display("FAIL case=%0d rst=%b en=%b a=%0d b=%0d expected=%0d got=%0d",
                 cases,rst,en,a,b,expected,q);
        $fatal(1);
      end
      #4; clk=0;
    end
  endtask
  initial begin
    tick(1,1,255,255);
    for (x=0; x<256; x=x+1)
      for (y=0; y<256; y=y+1) tick(0,1,x,y);
    tick(0,0,0,0);       // hold nonzero state despite new operands
    tick(1,1,255,255);   // reset must win over enabled overflowing sum
    tick(0,0,255,255);   // hold reset state
    for (i=0; i<32; i=i+1) begin
      tick(0,1,i,200);
      tick(0,0,255,255);
      tick(1,1,100,100);
    end
    $display("PASS cases=%0d exhaustive_operand_pairs=65536", cases);
    $finish;
  end
endmodule
