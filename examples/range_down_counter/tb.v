module tb;
reg clk=0,reset=0,clear=0,enable=0;
reg [4:1] step=0;
wire [8:1] count;
integer expected=0,samples=0,mismatches=0,a,b;
RangeCounter dut(.clk(clk),.reset(reset),.clear(clear),.enable(enable),.step(step),.count(count));
task tick;
input r,c,e; input [3:0] s;
begin
 clk=0;reset=r;clear=c;enable=e;step=s;#5;
 if(r || c) expected=0;else if(e) expected=(expected-s)&255;
 clk=1;#1;samples=samples+1;
 if(count !== expected[7:0]) begin mismatches=mismatches+1;if(mismatches<8)$display("bad sample=%0d expected=%0d count=%0d",samples,expected,count);end
 #4;clk=0;
end
endtask
initial begin
 tick(1,1,1,15);
 for(a=0;a<16;a=a+1) begin
  tick(1,0,1,a);
  for(b=0;b<256;b=b+1)tick(0,0,1,a);
  tick(0,0,0,15);tick(0,1,1,15);tick(0,1,0,15);
 end
 $display("RANGE_COUNTER_RESULT mismatches=%0d samples=%0d",mismatches,samples);if(mismatches) $fatal(1,"subtraction mismatch");$finish;
end
endmodule
