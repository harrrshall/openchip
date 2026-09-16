module tb;
reg clk=0, reset=0;
reg [7:0] in=0;
wire done;
TopModule dut(.*);
integer seq,idx,word,remaining=0,expected=0,samples=0,mismatches=0;
reg initialized=0;
task check;
begin
samples=samples+1;
if(done !== expected[0]) begin
 mismatches=mismatches+1;
 if(mismatches<10)$display("PACKET mismatch seq=%0d step=%0d reset=%b in=%h done=%b expected=%b",seq,idx,reset,in,done,expected[0]);
end
end
endtask
task tick(input rst,input [7:0] data);
begin
clk=0;reset=rst;in=data;#2;
check; // A synchronous reset must not change done before the edge.
if(rst)begin remaining=0;expected=0;end
else begin
 expected=0;
 if(remaining==0)begin if(data[3])remaining=2;end
 else if(remaining==1)begin remaining=0;expected=1;end
 else remaining=remaining-1;
end
clk=1;#2;check;clk=0;#1;
end
endtask
initial begin
// Establish reset once before measured observations.
reset=1;#2;clk=1;#2;clk=0;reset=0;#1;
for(seq=0;seq<4096;seq=seq+1)begin
 idx=-1;tick(1,0);
 for(idx=0;idx<12;idx=idx+1)begin
  word=((seq^(idx*73))&8'hf7)|(((seq>>idx)&1)<<3);
  tick(0,word[7:0]);
 end
 idx=12;tick(0,0);idx=13;tick(0,0);
end
$display("PACKET_RESULT mismatches=%0d samples=%0d",mismatches,samples);
if(mismatches != 0)$fatal(1,"Packet framing mismatch");
$finish;
end
endmodule
