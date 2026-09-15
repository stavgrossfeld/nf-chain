Output "assets/demo.gif"

Set FontSize 14
Set Width 950
Set Height 580
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Hide
Type "source ~/.zshrc >/dev/null 2>&1"
Enter
Type "export PATH=$PWD/.venv/bin:$PATH"
Enter
Type "clear"
Enter
Show

Type "cat examples/complex_chain.flow"
Sleep 300ms
Enter
Sleep 3s

Type "nf-chain explain examples/complex_chain.flow"
Sleep 300ms
Enter
Sleep 3.5s

Type "nf-chain run examples/complex_chain.flow --stub-run --tower"
Sleep 300ms
Enter
Sleep 6s
