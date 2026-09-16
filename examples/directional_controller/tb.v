module tb;
reg clk=0, areset=0,bump_left=0,bump_right=0,ground=1,dig=0;
wire walk_left,walk_right,aaah,digging;
TopModule dut(.*);
integer state, mode, bits, samples=0, mismatches=0;
// State IDs: walking left/right 0/1, falling left/right 2/3, digging left/right 4/5.
task check;
reg [3:0] expected;
begin
case(state)
0: expected=4'b1000;
1: expected=4'b0100;
2,3: expected=4'b0010;
4,5: expected=4'b0001;
endcase
samples=samples+1;
if ({walk_left,walk_right,aaah,digging} !== expected) begin
 mismatches=mismatches+1;
 if(mismatches<10) $display("Mismatch state=%0d input=%b%b%b%b actual=%b expected=%b",state,bump_left,bump_right,ground,dig,{walk_left,walk_right,aaah,digging},expected);
end
end
endtask
task tick(input bl,input br,input g,input d);
begin
clk=0;bump_left=bl;bump_right=br;ground=g;dig=d;#2;
case(state)
0: if(!g)state=2;else if(d)state=4;else if(bl)state=1;
1: if(!g)state=3;else if(d)state=5;else if(br)state=0;
2: if(g)state=0;
3: if(g)state=1;
4: if(!g)state=2;
5: if(!g)state=3;
endcase
clk=1;#2;clk=0;#1;
end
endtask
initial begin
for(mode=0;mode<6;mode=mode+1)begin
 for(bits=0;bits<16;bits=bits+1)begin
  clk=0;areset=0;#1;areset=1;state=0;#2;check;areset=0;#1;
  if(mode==1||mode==3||mode==5)tick(1,0,1,0);
  if(mode==2||mode==3)tick(0,0,0,0);
  if(mode==4||mode==5)tick(0,0,1,1);
  tick(bits[3],bits[2],bits[1],bits[0]);check;
  tick(0,0,0,0);check;
  tick(0,0,1,0);check;
 end
end
$display("STATE_RESULT mismatches=%0d samples=%0d",mismatches,samples);
if (mismatches != 0) $fatal(1, "Controller transition mismatch");
$finish;
end
endmodule
