module tb;
reg clk=0,reset=0,in=0;wire disc,flag,err;TopModule dut(clk,reset,in,disc,flag,err);
reg [7:0] history=0;reg [2:0] expected;integer mismatches=0,samples=0,pattern,k,n;
task step;input rst;input bit_in;begin
 clk=0;reset=rst;in=bit_in;#2;clk=1;
 if(rst)begin history=0;expected=0;end
 else begin history={history[6:0],bit_in};expected={history[6:0]==7'b0111110,history==8'b01111110,history[6:0]==7'b1111111};end
 #2;samples=samples+1;if({disc,flag,err} !== expected)mismatches=mismatches+1;
 clk=0;#2;samples=samples+1;if({disc,flag,err} !== expected)mismatches=mismatches+1;
end endtask
initial begin
 for(pattern=0;pattern<4096;pattern=pattern+1)begin
  step(1,pattern&1);
  for(k=0;k<12;k=k+1)step(0,(pattern>>k)&1);
  step(0,0);step(0,0);
 end
 for(n=0;n<16;n=n+1)begin
  step(0,0);for(k=0;k<6;k=k+1)step(0,1);step(0,0);
  for(k=0;k<5;k=k+1)step(0,1);step(0,0);
 end
 for(k=0;k<64;k=k+1)step(0,1);
 step(1,1);step(0,1);step(0,0);
 for(n=0;n<9;n=n+1)begin
  step(1,0);for(k=0;k<n;k=k+1)step(0,1);step(1,1);step(0,0);
 end
 $display("HDLC_RESULT mismatches=%0d samples=%0d",mismatches,samples);
 if(mismatches)$fatal(1,"HDLC mismatch");$finish;
end
endmodule
