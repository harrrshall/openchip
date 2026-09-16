module tb;
reg clk=0,resetn=0,in=0;wire out;
reg [3:0] expected=0;
integer samples=0,mismatches=0,seq,idx;
TopModule dut(.clk(clk),.resetn(resetn),.in(in),.out(out));
task check;
begin
 samples=samples+1;
 if(out !== expected[3])begin
  mismatches=mismatches+1;
  if(mismatches<8)$display("SHIFT mismatch seq=%0d sample=%0d resetn=%b in=%b out=%b expected=%b",seq,samples,resetn,in,out,expected[3]);
 end
end
endtask
task tick;
input rn,bit_in;
begin
 clk=0;resetn=rn;in=bit_in;#5;check;
 if(!rn)expected=0;else expected={expected[2:0],bit_in};
 clk=1;#1;check;#4;clk=0;
end
endtask
initial begin
 #5;clk=1;#5;clk=0;
 for(seq=0;seq<256;seq=seq+1)begin
  tick(0,1);
  for(idx=0;idx<8;idx=idx+1)tick(1,(seq>>idx)&1);
  tick(0,1);tick(0,0);tick(1,1);
 end
 $display("SHIFT_RESULT mismatches=%0d samples=%0d",mismatches,samples);
 if(mismatches)$fatal(1,"shift mismatch");$finish;
end
endmodule
