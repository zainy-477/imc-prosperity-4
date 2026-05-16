
# IMC Prosperity 4 - Rocky Mountain Goats
This writeup shares our strategies for the algorithmic and manual challenges of IMC Prosperity 4 (2026), which brought us to a global rank of 154th out of 18000+ teams - with a total score of 485,221 XIRECs in Phase 1 and 531,123 XIRECs in Phase 2. This was the first attempt at a quantitative trading competition for all of us, and we formed a team through the Discord server created by IMC for this competition. 

> Team Members: Zain Hirji, Alex Zhang, Saksham Arora, Annanye Naik

| Zain Hirji | Saksham Arora |
|---|---|
| <img width="1272" height="1696" alt="WhatsApp Image 2026-05-13 at 22 33 33" src="https://github.com/user-attachments/assets/7020f011-6cab-476a-9c4e-360c6d51a901" /> | <img width="2160" height="2880" alt="image" src="https://github.com/user-attachments/assets/7e46786f-7163-4b6f-bb2a-ba303ed64177" /> |

## Competition Overview

Briefly explain the structure of Prosperity 4.

- 5 rounds
- Algorithmic + manual challenges

<table>
  <tr>
    <th colspan="4" align="center">Qualifying - Phase 1 Results (485,221 XIRECs)</th>
  </tr>
  <tr>
    <th>Round</th>
    <th>Algorithmic</th>
    <th>Manual</th>
    <th>Overall Rank</th>
  </tr>
  <tr>
    <td align="center">1</td>
    <td align="center">105,692</td>
    <td align="center">87,995</td>
    <td align="center">90th</td>
  </tr>
  <tr>
    <td align="center">2</td>
    <td align="center">77,667</td>
    <td align="center">213,867</td>
    <td align="center">277th</td>
  </tr>
</table>


<table>
  <tr>
    <th colspan="4" align="center">Final - Phase 2 Results (531,123 XIRECs)</th>
  </tr>
  <tr>
    <th>Round</th>
    <th>Algorithmic</th>
    <th>Manual</th>
    <th>Overall Rank</th>
  </tr>
  <tr>
    <td align="center">3</td>
    <td align="center">202,131</td>
    <td align="center">70,684</td>
    <td align="center">84th</td>
  </tr>
  <tr>
    <td align="center">4</td>
    <td align="center">149,166</td>
    <td align="center">38,814</td>
    <td align="center">92nd</td>
  </tr>
    <tr>
    <td align="center">5</td>
    <td align="center">-43,997</td>
    <td align="center">114,325</td>
    <td align="center">154th</td>
  </tr>
</table>



## Structural Overview
Contents


# Round 1

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
The first manual challenge of the competition was a trivial optimisation. We were given static orderbooks for two products - **DRYLAND FLAK** and **EMBER MUSHROOM** - and had to submit our own buy or sell order for each, at a chosen price and quantity. The exchange would then select a single clearing price that maximised the total traded volume from the orderbook (including the orders that we submitted) and broke ties by choosing the higher price. Our orders would be executed at this clearing price. Finally, we would be able to sell any inventory that we had acquired at fixed prices of 30 XIRECs for **DRYLAND FLAK** and 20 XIRECs for **EMBER MUSHROOM**, with a 0.10 XIREC trading fee per unit subtracted from the latter. 

We created Python code to numerically optimise this problem, and submitted the following two orders:
* Buy **DRYLAND FLAK** at a price of 30 XIRECs and volume of 9999 units.
* Buy **EMBER MUSHROOM** at a price of 17 XIRECs and volume of 19999 units.

This was one of the optimal solutions and as a result we came joint first in Round 1 of Manual. While this posed a problem that could easily be solved by brute force programming, it is interesting to think about why we obtain the results we do. For example, take a look at the volume of units we chose for our orders - if we were to increase these by 1, the clearing price would have increased by 1 XIREC and our profit would have shrunk by a large margin.

# Round 2

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
This manual challenge introduced an element of game theory. The premise was simple. We were given a budget of 50,000 XIRECs which we were able to split across three pillars (Research, Scale, Speed), each of which output a  multiplier according to our investment. An integer percentage X had to be allocated to each pillar, which would produce the following multiplier: 
* **Research(X)** = 200,000 $\cdot$ $\frac{\log(1 + X)}{\log(1 + 100)}$. This grows logarithmically from 0 to 200,000.
* **Scale(X)** = 7 $\cdot$ $\frac{X}{100}$. This grows linearly from 0 to 7.
* **Speed was rank-based across all players.** *The lowest speed investment would receive a multiplier of 0.1 and the highest speed investment would receive a multiplier of 0.9, while everyone inbetween would recieve a multiplier linearly scaled by rank.*

The final profit would be assigned via **PnL = (Research $\times$ Scale $\times$ Speed) - Budget_Used**.

For a given Speed investment, the remaining Research and Speed could be numerically optimised (the optimal strategy was always to use all of the allocated budget). Thus, our strategy revolved around trying to predict the multiplier one would receive for a given Speed investment. 

We assumed that a number of teams would invest nothing into Speed and that another large portion would bid up to 10% in order to try and overcut others. Furthermore, we predicted that a second large wave of teams around the 30% - 40% mark who would try to reach into the upper echelons of the multiplier by outbidding all 'sensible' investments. In the discord server and indeed from within our own team, the optimal Speed investment, as dictated by game theory, emerged to be 37%. As a result, many of us wanted incorporate a small increase to 38% or 39% as a safety factor. However, by recognising ourselves as a part of the 'game', we ultimately decided to go beyond what we thought was necessary and invest 45% into Speed. This resulted in optimal Research and Scaling investments of 14% and 41% respectively.

<table>
  <tr>
    <th colspan="4" align="center">Invest & Expand - Round 2 Manual Challenge</th>
  </tr>
  <tr>
    <th>Pillar</th>
    <th>Investment</th>
    <th>Multiplier</th>
  </tr>
  <tr>
    <td align="center">Research</td>
    <td align="center">14%</td>
    <td align="center">117,356 XIRECs</td>
  </tr>
  <tr>
    <td align="center">Scale</td>
    <td align="center">41%</td>
    <td align="center">$\times$ 2.9</td>
  </tr>
    <tr>
    <td align="center">Speed</td>
    <td align="center">45%</td>
    <td align="center">$\times$ 0.78</td>
  </tr>
</table>

This resulted in an overall profit of **213,867 XIRECs**, compared to the optimal *217,869 XIRECs* had we invested the optimal 42% in Speed, so we were very happy with our decision. Though, in hindsight, we should have considered that round-number bias caused large spikes in teams to choose multiples of 5% for investment in Speed, and gone slightly lower!


# Round 3

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
This was very similar to last years' Round 3 manual challenge, in Prosperity 3. There were a number of counterparties willing to sell the **ORNAMENTAL BIO-POD** product, each with a reserve price above which they would accept a bid. *Their distribution of asks was uniformly distributed at increments of 5 between 670 and 920 XIRECs.* We would later be able to sell all inventory at 920 XIRECs. 

We were allowed to submit two bids. The first bid had no strings attached and was thus a pure optimisation problem. However, if our second bid was lower than or equal to the mean of second bids of all players, our PnL would be penalised by a cubic penalty $\left(\frac{920-\text{avg-b2}}{920-b2}\right)^3$. As the first bid was dependent on the second bid, it could only be optimised after we chose our second bid.


The Nash equilibrium occured for a first bid of 751 XIRECs and a second bid of 836 XIRECs. Based on last years' results, where the average of 287 had only been slighly above the optimum of 284, we naively chose to submit a second bid of 846 XIRECs and corresponding optimal first bid of 756 XIRECs. The average second bid ended up being **859 XIRECs** and so we were heavily penalised, resulting in a PnL of **70,864 XIRECs** as opposed to the optimal *~80,000 XIRECs* - luckily, not a significant difference.

In hindsight, we should have anticipated the aggressive behaviour of players from the Round 2 manual challenge. In addition, the loss in profit for increasing the second bid was relatively low, which may have incentivised many teams to bid much higher than they had last year.


# Round 4

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
This challenge introduced us to the **AETHER CRYSTAL** product as well as a variety of options, as seen in the image below. The important things to note about options and these ones specifically are:
* An option is a contract that gives the buyer the right (but not obligation) to buy or sell an underlying asset at a specific price (called the strike price of the option) within a certain timeframe.
* A **CALL Option** gives the right to buy while a **PUT Option** gives the right to sell.
* At expiry, the CALL options are "in the money" if the underlying price is above their strike price (your profit per option = underlying price - strike price) or worthless if the underlying price is below their strike price (you make a loss if you purchase the asset above its price). Similar logic can be applied to PUT options.
* The **CHOOSER Option** converts to the side that is "in the money" at a certain time before expiry (e.g. if the underlying price is above the strike price 7 days before expiry, it converts to a CALL option) and expires like a standard PUT or CALL Option. 
* The **BINARY PUT Option** operates similar to a PUT option, except it pays a fixed amount if the option is "in the money" at expiry.
* The **KNOCK-OUT PUT Option** will have a strike price and a *barrier price below the strike price*. If the value of the underlying asset ever falls beneath the barrier price, the option is knocked-out and expires worthless. However, if this barrier price is never breached then the option expires as a standard PUT option.

<img width="1389" height="1221" alt="image" src="https://github.com/user-attachments/assets/1a293d4e-2ca0-47f3-9324-2bf6fe5152fe" />
<br><br>

The underlying **AETHER CRYSTAL** would be simulated using Geometric Brownian Motion with zero risk-neutral drift and a fixed annualised volatility of 251%, assuming 252 trading days per year. In addition, prices would evolve on a discrete grid of 4 steps per trading day. Our final score would be the average PnL across 100 simulations of the underlying, **which is a very small sample size with huge variance**.  

We tackled this challenge via a two-stage process. The first was to estimate the fair value of each option contract (which had a size of 3,000) and determine whether there were any contracts that were valued above the ask or below the bid, from which we could expect to make a profit. The second was to hedge our exposure to the market, due to the large volatility that we expected from our result. Hedging is a strategy used to reduce risk and limit potential losses; essentially, it involves taking an opposite position in a related asset, so that if one investment loses money then the other gains money.

The **Black-Shoales method** is a formula used to estimate the current fair value of an option. It can be used for regular call and put options, as well as binary options. The remaining chooser and knock-out put options had no mathematical equivalent, so we simulated results over multiple runs to calculate their expected value. Based on these expected values, we chose an initial set of options for investment to maximise expected value (i.e. mean profit from the 100 simulation runs) and obtained the following distributions:

<p>
  <img src="https://github.com/user-attachments/assets/d36f7d78-596c-4f0f-9605-f2f803ac287b" width="63%" />
  <img src="https://github.com/user-attachments/assets/4b3b6e1c-d31a-4fbf-a6b8-062ddcf84877" width="33%" />
</p>

Our main concern was the low expected value from the 60 CALL (3 week) option, around 2000 XIRECs (out of a 160000+ XIREC total mean), and its large negative tail. As a result, we made the decision to exclude it from our final submission. As seen in the statistics below, this would increase our win percentage (scenarios in which we were profitable) by 5% and significantly reduce our loss in the worst-case scenarios, with only a small decrease in mean profit. The flip side to this was a large decrease in the median profit, due to the volatility of this option, but we were willing to accept that. This is because we assumed the Prosperity team would recompute the scenario if excessive profits were achieved, so results would be biased toward lower profits.

| With 60 CHOOSER | Without 60 CHOOSER |
|---|---|
| ![](https://github.com/user-attachments/assets/66000f1a-baf4-4118-9b0a-0a6c571cde52) | ![](https://github.com/user-attachments/assets/4b4a7f54-711e-41c1-82b2-ccb30116fdac) |

Finally, we focussed on hedging. Initially, we tried to reason through the options we should choose for hedging and the quantity to buy or sell. These provided improved results as we figured out the options to hedge against our current selection, but the complexity of available options meant that we were unable to nail down the best quantities. Therefore, we ran a grid search across the options that offered us the best hedging options, and ended up submitting the following:
* Buy 50 x 50 PUT (2 week) option [PROFITABLE]
* Buy 50 x 50 CALL (2 week) option [PROFITABLE]
* Sell 50 x 50 CHOOSER (2/3 week) option [PROFITABLE]
* Sell 50 x 40 BINARY PUT (3 week) option [PROFITABLE]
* Buy 500 x 45 KNOCKOUT PUT (3 week) option [PROFITABLE]
* Buy 25 x 50 CALL (3 week) option [HEDGING]
* Buy 50 x 45 PUT (3 week) option [HEDGING]

| Max Mean Profit (without 60 CHOOSER) | Final Submission |
|---|---|
| ![](https://github.com/user-attachments/assets/4b4a7f54-711e-41c1-82b2-ccb30116fdac) | ![](https://github.com/user-attachments/assets/9ede53cb-2f53-45d3-a617-025757354f37) |

At a small cost to the mean and median profit, our hedging choices significantly reduced our worst case scenarios and improved our win percentage by a further 4%, which we belived to be essential in a game where the team was likely to be incentivised to punish high volatility. Higher win rates were possible, but we didn't believe the drop in expected value to be worth it. Unfortunately, even with hedging, there was a large portion of luck involved in this round - the most of any manual round, by a large margin. The team that obtained the highest profit in Round 4 Manual, *PigameforTrading*, went on to win the Manual Challenge. We particularly liked the following analogy, posted by someone on the discord:

<img width="1090" height="143" alt="image" src="https://github.com/user-attachments/assets/f9acab12-e8bd-4ac3-bf3e-704812c902ef" />

In the end, we obtained a profit of **38,814 XIRECs**, compared to the mean *2,310 XIRECs*, median *22,618 XIRECs*, and maximum *177,980 XIRECs*. Although this was a little disappointing, we were happy with our strategy and would not have changed it if given the chance to repeat the round with a different seed.

# Round 5

## Algorithmic Challenge
Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

## Manual Challenge
Describe:
- our thought process
- the tools we used
- how decisions were made


# Takeaways
