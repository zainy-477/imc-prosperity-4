
# IMC Prosperity 4 - Rocky Mountain Goats
This writeup shares our strategies for the algorithmic and manual challenges of IMC Prosperity 4 (2026), which brought us to a global rank of 154th out of 22000+ teams - with a total score of 485,221 XIRECs in Phase 1 and 531,123 XIRECs in Phase 2. This was the first attempt at a quantitative trading competition for all of us, and we formed a team through the Discord server created by IMC for this competition. 

> Team Members: Alex Zhang, Annanye Naik, Saksham Arora, Zain Hirji

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
The first manual challenge of the competition was a trivial optimisation. We were given static orderbooks for two products - **DRYLAND_FLAK** and **EMBER_MUSHROOM** - and had to submit our own buy or sell order for each, at a chosen price and quantity. The exchange would then select a single clearing price that maximised the total traded volume from the orderbook (including the orders that we submitted) and broke ties by choosing the higher price. Our orders would be executed at this clearing price. Finally, we would be able to sell any inventory that we had acquired at fixed prices of 30 XIRECs for **DRYLAND_FLAK** and 20 XIRECs for **EMBER_MUSHROOM**, with a 0.10 XIREC trading fee per unit subtracted from the latter. 

We created Python code to numerically optimise this problem, and submitted the following two orders:
* Buy **DRYLAND_FLAK** at a price of 30 XIRECs and volume of 9999 units.
* Buy **EMBER_MUSHROOM** at a price of 17 XIRECs and volume of 19999 units.

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

In hindsight, we should have anticipated the aggressive behaviour of players from the Round 2 manual challenge. In addition, the penalty for increasing the second bid was relatively low, which may have incentivised many teams to bid much higher than they had last year.


# Round 4

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
