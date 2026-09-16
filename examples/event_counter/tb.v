module tb;
reg clk=0,reset_n=1,clear=0,enable=0;wire[7:0]q;
integer expected=0,checks=0,errors=0,n;
event_counter dut(.clk(clk),.reset_n(reset_n),.clear(clear),.enable(enable),.q(q));always #5 clk=~clk;
task observe;begin checks=checks+1;if(q!==expected[7:0])errors=errors+1;end endtask
task cycle;input integer c,e;begin
 @(negedge clk);clear=c;enable=e;
 if(!reset_n || c)expected=0;else if(e && expected<255)expected=expected+1;
 @(posedge clk);#1;observe;
end endtask
task reset_between_edges;begin
 @(negedge clk);clear=0;enable=0;#2;reset_n=0;expected=0;#1;observe;#1;reset_n=1;
end endtask
initial begin
 reset_between_edges;
 for(n=0;n<300;n=n+1)cycle(0,1);
 for(n=0;n<8;n=n+1)cycle(0,0);
 cycle(1,1);cycle(0,1);
 reset_between_edges;
 for(n=0;n<40;n=n+1)begin cycle(0,n%2);cycle(n%7==0,1);end
 @(negedge clk);clear=1;enable=1;#2;reset_n=0;expected=0;#1;observe;
 cycle(1,1);cycle(0,1);
 $display("RESET_RESULT mismatches=%0d samples=%0d",errors,checks);$finish;
end
endmodule
